"""S25 服务层：预检（零写入）→ 令牌 → 提交 → 错误工作簿。

关键安全设计
------------
1. **预检零业务写入**：``preview()`` 不创建任何数据库记录，只返回摘要与签名令牌。
   令牌绑定 *文件摘要 + schema 版本 + 引擎版本 + 操作者 + 过期时间*。
2. **防 TOCTOU**：``commit()`` 重新计算文件摘要与操作者，与令牌比对；
   同时**重新解析并重新校验**，不信任预检时提交的任何行数据。
3. **提交幂等**：重复提交同一文件不会产生重复业务数据（第二次全部 skipped）；
   数据库唯一约束是最后一道防线。
4. **错误可下载**：错误以工作簿形式导出，含原始行值与错误码。
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from django.core import signing
from django.utils import timezone

from .parsing import ParseError, parse
from .schema import ENGINE_VERSION, DatasetSchema, ValidationResult, get


def _adapter(dataset: str):
    """延迟导入适配器。

    适配器依赖具体业务 app（如 ``smass_organization``）。只有当某个 settings
    真的安装了那个 app 时才可用；因此不在模块顶层 import，避免
    "装了引擎但没装业务 app" 的环境直接 ImportError。
    """
    from .adapters import get_adapter

    return get_adapter(dataset)

#: 预检令牌有效期（秒）
TICKET_TTL_SECONDS = 30 * 60

_TICKET_SALT = 'smass.data_exchange.preview'


class TicketError(ValueError):
    """预检令牌无效/过期/与内容不匹配。"""

    def __init__(self, message, code='TICKET_INVALID'):
        self.code = code
        super().__init__(message)


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _actor_key(account) -> str:
    if account is None:
        return 'anonymous'
    pk = getattr(account, 'pk', None)
    return 'account:{}'.format(pk) if pk is not None else 'anonymous'


def _is_anonymous(account) -> bool:
    return account is None or not getattr(account, 'is_authenticated', False)


# ---------------------------------------------------------------------------
# 令牌
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreviewTicket:
    dataset: str
    schema_version: str
    engine_version: str
    digest: str
    actor: str
    issued_at: int


def issue_ticket(schema: DatasetSchema, digest: str, account) -> str:
    payload = {
        'ds': schema.code,
        'sv': schema.version,
        'ev': ENGINE_VERSION,
        'dg': digest,
        'ac': _actor_key(account),
        'ts': int(timezone.now().timestamp()),
    }
    return signing.dumps(payload, salt=_TICKET_SALT, compress=True)


def read_ticket(token: str) -> PreviewTicket:
    try:
        payload = signing.loads(token, salt=_TICKET_SALT, max_age=TICKET_TTL_SECONDS)
    except signing.SignatureExpired:
        raise TicketError('预检已过期，请重新预检', code='TICKET_EXPIRED')
    except signing.BadSignature:
        raise TicketError('预检令牌无效（可能被篡改）', code='TICKET_BAD_SIGNATURE')
    return PreviewTicket(
        dataset=payload['ds'], schema_version=payload['sv'],
        engine_version=payload['ev'], digest=payload['dg'],
        actor=payload['ac'], issued_at=int(payload.get('ts', 0)),
    )


# ---------------------------------------------------------------------------
# 预检
# ---------------------------------------------------------------------------
def preview(content: bytes, filename: str, dataset: str, account, *,
            request=None) -> dict:
    """解析 + 校验 + 差异统计；**不写任何业务数据**。"""
    schema = get(dataset)
    adapter = _adapter(dataset)

    result = ValidationResult(schema=schema)

    try:
        parsed, meta, struct_errors = parse(content, filename, schema)
    except ParseError as exc:
        return {
            'ok': False,
            'ticket': None,
            'summary': {
                'dataset': schema.code, 'schema_version': schema.version,
                'engine_version': ENGINE_VERSION, 'total': 0, 'ok': 0, 'errors': 1,
            },
            'errors': [{'row': exc.row, 'column': exc.column,
                        'code': exc.code, 'message': str(exc)}],
            'diff': [],
            'meta': {'parse_error': exc.code},
        }

    result.total = len(parsed)
    result.errors.extend(_dedupe(struct_errors))

    # 业务校验（外键存在性、库内唯一性、字段级授权）
    validated, biz_errors = adapter.validate(parsed, account, request=request)
    result.errors.extend(_dedupe(biz_errors))

    bad_rows = {e['row'] for e in result.errors}
    result.error_count = len(bad_rows)
    result.ok_count = max(0, result.total - result.error_count)

    for row in validated:
        plan = row.get('__plan__')
        if plan == 'create':
            result.created += 1
        elif plan == 'update':
            result.updated += 1
        elif plan == 'conflict':
            result.conflict += 1
        else:
            result.skipped += 1

    digest = file_digest(content)
    ticket = issue_ticket(schema, digest, account)

    # 差异预览：只暴露调用者有字段权限的部分
    diff = [adapter.describe_row(row, account) for row in validated[:200]]

    return {
        'ok': not result.has_errors,
        'ticket': ticket,
        'summary': result.summary(),
        'errors': result.errors[:500],
        'diff': diff,
        'meta': meta,
        'digest': digest,
    }


def _dedupe(errors):
    seen = set()
    out = []
    for e in errors:
        key = (e.get('row'), e.get('column'), e.get('code'), e.get('message'))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _record_failed_job(errors, account, dataset):
    """把一次因错误被拒绝的提交记录成作业 + 行错误。

    目的是让"导入历史"能看到失败批次，并能下载对应的错误工作簿。
    业务 app 未安装时静默跳过（引擎仍可用，只是没有历史）。
    """
    try:
        from smass_organization.models import (
            IMPORT_FAILED,
            DataImportJob,
            DataImportRowError,
        )
    except Exception:  # noqa: BLE001 - 未安装业务 app
        return None

    bad_rows = len({e.get('row') for e in errors})
    job = DataImportJob.objects.create(
        kind=dataset[:32],
        status=IMPORT_FAILED,
        total_rows=bad_rows,
        success_rows=0,
        error_rows=bad_rows,
        created_by=_actor_key(account)[:32],
    )
    for e in errors[:1000]:
        DataImportRowError.objects.create(
            job=job,
            row_number=int(e.get('row') or 0),
            column=str(e.get('column') or '')[:64],
            error_code=str(e.get('code') or 'ERROR')[:32],
            message=str(e.get('message') or '')[:255],
        )
    return job


def load_job_errors(job_id):
    """按作业读取错误清单（用于错误工作簿下载与历史展示）。"""
    try:
        from smass_organization.models import DataImportJob, DataImportRowError
    except Exception:  # noqa: BLE001
        return None, []

    job = DataImportJob.objects.filter(pk=job_id).first()
    if job is None:
        return None, []

    rows = (
        DataImportRowError.objects
        .filter(job=job)
        .order_by('row_number', 'pk')
        .values('row_number', 'column', 'error_code', 'message')
    )
    errors = [{
        'row': r['row_number'],
        'column': r['column'],
        'code': r['error_code'],
        'message': r['message'],
    } for r in rows]
    return job, errors


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------
def commit(token: str, content: bytes, filename: str, dataset: str, account, *,
           request=None, allow_partial=False) -> dict:
    """校验令牌 -> 重新解析校验 -> 写库 -> 返回统计。

    ``allow_partial=False``（默认）时，只要存在任何错误行就整体拒绝，
    避免"一半进一半不进"的不可解释状态。
    """
    schema = get(dataset)
    adapter = _adapter(dataset)

    ticket_data = read_ticket(token)

    # ---- 令牌绑定校验 ----
    if ticket_data.dataset != schema.code:
        raise TicketError('令牌与数据集不匹配', code='TICKET_DATASET_MISMATCH')
    if ticket_data.schema_version != schema.version:
        raise TicketError(
            '模板版本已变化（{} -> {}），请重新预检'.format(
                ticket_data.schema_version, schema.version),
            code='TICKET_SCHEMA_CHANGED')
    if ticket_data.engine_version != ENGINE_VERSION:
        raise TicketError('引擎版本已变化，请重新预检', code='TICKET_ENGINE_CHANGED')
    if ticket_data.actor != _actor_key(account):
        raise TicketError('令牌不属于当前操作者', code='TICKET_ACTOR_MISMATCH')

    digest = file_digest(content)
    if digest != ticket_data.digest:
        raise TicketError(
            '文件内容与预检时不一致（可能被替换），请重新预检',
            code='TICKET_DIGEST_MISMATCH')

    # ---- 重新解析并重新校验（不信任预检结果）----
    try:
        parsed, meta, struct_errors = parse(content, filename, schema)
    except ParseError as exc:
        raise TicketError('重新解析失败：{}'.format(exc), code=exc.code)

    validated, biz_errors = adapter.validate(parsed, account, request=request)
    errors = _dedupe(list(struct_errors) + list(biz_errors))

    if errors and not allow_partial:
        # 失败也建作业并落错误，保证"导入历史 + 错误工作簿下载"可用
        job = _record_failed_job(errors, account, dataset)
        return {
            'ok': False,
            'committed': False,
            'job_id': getattr(job, 'pk', None),
            'batch_id': str(getattr(job, 'batch_id', '')),
            'errors': errors[:500],
            'error_count': len({e['row'] for e in errors}),
            'summary': {
                'dataset': schema.code, 'schema_version': schema.version,
                'total': len(parsed), 'errors': len({e['row'] for e in errors}),
            },
        }

    job, stats = adapter.commit(validated, account, request=request)

    return {
        'ok': True,
        'committed': True,
        'job_id': getattr(job, 'pk', None),
        'batch_id': str(getattr(job, 'batch_id', '')),
        'stats': stats,
        'meta': meta,
        'errors': errors[:200],
    }


# ---------------------------------------------------------------------------
# 错误工作簿
# ---------------------------------------------------------------------------
def build_error_workbook(errors, dataset: str, *, original_rows=None) -> bytes:
    """把错误清单导出为 xlsx，便于用户逐行修正后重传。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    schema = get(dataset)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Errors'

    headers = ['行号', '列', '错误码', '说明']
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='FDE9E9')

    for index, err in enumerate(errors, start=2):
        ws.cell(row=index, column=1, value=err.get('row', 0))
        ws.cell(row=index, column=2, value=err.get('column', ''))
        ws.cell(row=index, column=3, value=err.get('code', ''))
        ws.cell(row=index, column=4, value=_neutralize(str(err.get('message', ''))))

    for col, width in zip('ABCD', (8, 18, 20, 60)):
        ws.column_dimensions[col].width = width

    # 第二张表：修正指引（回填后可直接重传）
    guide = wb.create_sheet('Guide')
    guide.append(['字段', '中文名', '必填', '类型', '可选值', '说明'])
    for cell in guide[1]:
        cell.font = Font(bold=True)
    for f in schema.fields:
        guide.append([f.code, f.label, '是' if f.required else '否', f.dtype,
                      '/'.join(f.choices) or '', f.help])
    for col, width in zip('ABCDEF', (18, 18, 8, 10, 24, 46)):
        guide.column_dimensions[col].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


#: Excel 公式注入前缀字符
_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r', '\n')


def _neutralize(text: str) -> str:
    """中和公式注入：文本单元格前加单引号。"""
    if not text:
        return text
    if text[0] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def neutralize_row(values):
    return [_neutralize('' if v is None else str(v)) for v in values]
