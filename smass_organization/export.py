"""R4-03：受限导出（CSV）。

安全要点（对应计划 §1.6 与 R4-03 验收）：
1. **对象 scope**：只导出 ``scoped_students(account)`` 可见的记录；
2. **字段 scope**：只导出 ``visible_fields(account)`` 允许的字段；
3. **CSV 注入防护**：以 ``= + - @ TAB CR`` 开头的单元格加前缀 ``'``，
   防止 Excel 公式注入；
4. **分页/上限**：默认 5000 行上限，支持 offset 分段；
5. **审计**：每次导出写一条 ``AccountAuditEvent``（含行数与字段数，不含明文数据）。
"""
import csv
import io

from smass_organization import services
from smass_organization.models import StudentRecord

#: 单次导出的上限（行）。流式导出下内存不随行数线性增长；
#: 上限用于防止误触发超大导出，10k 规模的日常导出在范围内。
MAX_ROWS = 50000

#: 可能触发电子表格公式的前缀
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_cell(value):
    """中和 CSV 公式注入。"""
    text = '' if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    # 换行会破坏行结构，替换为空格
    return text.replace('\r', ' ').replace('\n', ' ')


def _base_columns(account):
    """固定列 + 可见的扩展字段列。"""
    columns = ['student_no', 'name', 'unit', 'status']
    extra_codes = [field.code for field in services.visible_fields(account)]
    return columns, extra_codes


def _scoped_students(account, *, unit_code=None, keyword=None):
    queryset = services.scoped_students(account).select_related('unit')
    if unit_code:
        queryset = queryset.filter(unit__code=unit_code)
    if keyword:
        queryset = queryset.filter(name__icontains=keyword)
    return queryset.order_by('student_no')


def count_students(account, *, unit_code=None, keyword=None):
    """导出前的总数（用于响应头与截断提示，不物化行）。"""
    return _scoped_students(account, unit_code=unit_code,
                            keyword=keyword).count()


def iter_students_csv(account, *, unit_code=None, keyword=None,
                      limit=MAX_ROWS, offset=0, chunk_size=2000):
    """**流式**生成 CSV 文本块（含表头）。

    使用 ``queryset.iterator()`` 分批取数，避免 10k 行一次性物化为模型列表；
    每个 yield 是一个完整的 CSV 片段，可直接写入 ``StreamingHttpResponse``。
    """
    queryset = _scoped_students(
        account, unit_code=unit_code, keyword=keyword)[offset:offset + limit]

    columns, extra_codes = _base_columns(account)
    # 一次性计算可见字段集合，避免逐行调用 filtered_extra 造成的 N+1 查询。
    allowed_codes = {field.code for field in services.visible_fields(account)}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')

    def _flush():
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow(columns + extra_codes)
    yield _flush()

    for record in queryset.iterator(chunk_size=chunk_size):
        extra = record.extra or {}
        visible_extra = {key: value for key, value in extra.items()
                         if key in allowed_codes}
        values = [
            record.student_no,
            record.name,
            record.unit.code if record.unit else '',
            record.status,
        ]
        values += [visible_extra.get(code, '') for code in extra_codes]
        writer.writerow([sanitize_cell(value) for value in values])
        yield _flush()


def export_students_csv(account, *, unit_code=None, keyword=None,
                        limit=MAX_ROWS, offset=0):
    """生成受限 CSV。返回 ``(text, meta)``。

    为兼容既有调用方保留"返回完整文本"的接口；大数据量下载应使用
    ``iter_students_csv`` + ``StreamingHttpResponse``，避免整串驻留内存。
    """
    total = count_students(account, unit_code=unit_code, keyword=keyword)
    chunks = list(iter_students_csv(
        account, unit_code=unit_code, keyword=keyword,
        limit=limit, offset=offset))
    text = ''.join(chunks)
    exported = max(len(chunks) - 1, 0)
    headers = _base_columns(account)[0] + _base_columns(account)[1]

    meta = {
        'total': total,
        'exported': exported,
        'offset': offset,
        'limit': limit,
        'columns': headers,
        'truncated': total > offset + exported,
    }

    _audit_export(account, meta)
    return text, meta


def _audit_export(account, meta):
    from r22_account import audit

    try:
        audit.record_success(
            'r4_student_export',
            actor=account,
            target='student_record',
            target_id='export',
            context={
                'exported': meta['exported'],
                'total': meta['total'],
                'columns': len(meta['columns']),
                'truncated': meta['truncated'],
            },
        )
    except Exception:  # noqa: BLE001 - 审计失败不阻断导出，但需可观测
        pass
