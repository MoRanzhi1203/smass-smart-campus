"""S25 适配器：把各业务模块接到统一引擎上。

约定
----
适配器只负责**业务语义**：
- ``validate(rows, account)``：外键存在性、库内唯一性、业务状态合法性、
  以及调用者的导入权限；返回 ``(validated_rows, errors)``，其中每行额外带
  ``__plan__``（create / update / skip / conflict）。
- ``commit(validated, account)``：在一个事务里写库，写审计/变更历史，
  并返回 ``(job, stats)``。
- ``describe_row(row, account)``：给预检差异预览用，必须经过字段级裁剪。

适配器**不**做格式解析、不生成模板、不签发令牌——那些属于引擎。
"""
from __future__ import annotations

from smass_data_exchange.schema import DatasetSchema, register

#: dataset code -> adapter 实例
_ADAPTERS: dict[str, 'BaseAdapter'] = {}


class AdapterError(ValueError):
    """适配器注册/查找失败。"""


class BaseAdapter:
    dataset: str = ''
    schema: DatasetSchema = None
    #: 需要的导入权限动作（由 r21 authorization 判定）
    required_action = 'import'

    def validate(self, rows, account, *, request=None):
        raise NotImplementedError

    def commit(self, validated, account, *, request=None):
        raise NotImplementedError

    def describe_row(self, row, account):
        return {k: v for k, v in row.items() if not k.startswith('__')}


def register_adapter(adapter: BaseAdapter) -> BaseAdapter:
    if not adapter.dataset:
        raise AdapterError('adapter 必须声明 dataset')
    register(adapter.schema)
    _ADAPTERS[adapter.dataset] = adapter
    return adapter


def get_adapter(dataset: str) -> BaseAdapter:
    adapter = _ADAPTERS.get(dataset)
    if adapter is None:
        raise AdapterError('数据集 {} 尚无导入适配器'.format(dataset))
    return adapter


def all_adapters():
    return tuple(_ADAPTERS.values())


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _check_import_permission(account):
    """导入权限：走 S06 统一门面；无权限直接拒绝。"""
    from r21_account import authorization as authz

    if not authz.has_action(account, 'import'):
        raise authz.AuthzDenied('action_forbidden', action='import')
    return True


# ---------------------------------------------------------------------------
# R4：学生档案
# ---------------------------------------------------------------------------
class R4StudentAdapter(BaseAdapter):
    """学生档案导入（复用 smass_organization 的模型与字段定义）。"""

    dataset = 'r4_students'

    def __init__(self):
        from smass_data_exchange.schema import DatasetSchema, FieldSpec

        from smass_organization.models import StudentRecord

        statuses = tuple(choice[0] for choice in StudentRecord.status.field.choices)
        self.schema = DatasetSchema(
            code=self.dataset,
            version='1',
            title='学生档案导入（R4）',
            fields=(
                FieldSpec('student_no', '学号', required=True, max_length=20,
                          help='唯一，同名文件内不可重复',
                          example='DEMO-1001'),
                FieldSpec('name', '姓名', required=True, max_length=32,
                          help='真实使用时请使用授权数据；模板示例为构造值',
                          example='演示学生A'),
                FieldSpec('unit_code', '组织编码', max_length=64,
                          help='必须已存在的组织编码（班级/院系等）',
                          example='DEMO-K'),
                FieldSpec('status', '学籍状态', dtype='enum', choices=statuses,
                          help='留空默认 enrolled', example='enrolled'),
                FieldSpec('enrolled_at', '入学日期', dtype='date',
                          help='格式 YYYY-MM-DD', example='2024-09-01'),
            ),
            instructions=(
                '首行是表头，第 2 行为灰色示例行（导入时自动忽略）',
                '学号必填且文件内不可重复',
                '组织编码必须已存在，否则该行报 UNKNOWN_UNIT',
            ),
            notes=(
                '预检不写入任何数据；提交时若存在错误行默认整体拒绝',
                '同一文件重复提交不会产生重复档案（幂等）',
            ),
        )

    # ---------------- 校验 ----------------
    def validate(self, rows, account, *, request=None):
        from smass_organization.models import OrganizationUnit, StudentRecord

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], [{
                'row': 0, 'column': '', 'code': 'PERMISSION_DENIED',
                'message': '当前账号没有导入权限（{}）'.format(exc),
            }]

        valid_status = {choice[0] for choice in StudentRecord.status.field.choices}

        codes = {str(r.get('unit_code') or '').strip() for r in rows}
        codes.discard('')
        units = {
            u.code: u for u in OrganizationUnit.objects.filter(code__in=codes)
        }

        student_nos = {str(r.get('student_no') or '').strip() for r in rows}
        student_nos.discard('')
        existing = {
            s.student_no: s for s in StudentRecord.objects.filter(student_no__in=student_nos)
        }

        seen_in_file = set()
        validated = []
        errors = []

        for row in rows:
            line = row.get('__row__', 0)
            student_no = str(row.get('student_no') or '').strip()
            name = str(row.get('name') or '').strip()
            unit_code = str(row.get('unit_code') or '').strip()
            status = str(row.get('status') or '').strip() or 'enrolled'
            enrolled_at = row.get('enrolled_at') or None

            row_errors = []
            if not student_no:
                row_errors.append(('student_no', 'EMPTY_STUDENT_NO', '学号不能为空'))
            elif student_no in seen_in_file:
                row_errors.append(('student_no', 'DUPLICATE_IN_FILE', '文件内学号重复'))
            else:
                seen_in_file.add(student_no)

            if not name:
                row_errors.append(('name', 'EMPTY_NAME', '姓名不能为空'))

            if status not in valid_status:
                row_errors.append(('status', 'INVALID_STATUS', '非法学籍状态'))

            unit = None
            if unit_code:
                unit = units.get(unit_code)
                if unit is None:
                    row_errors.append(('unit_code', 'UNKNOWN_UNIT',
                                       '组织编码不存在: {}'.format(unit_code)))

            if row_errors:
                for column, code, message in row_errors:
                    errors.append({'row': line, 'column': column,
                                   'code': code, 'message': message})
                continue

            record = existing.get(student_no)
            if record is None:
                plan = 'create'
            elif (record.name == name
                  and (record.unit_id or None) == (unit.pk if unit else None)
                  and record.status == status):
                plan = 'skip'      # 无变化
            else:
                plan = 'update'

            item = dict(row)
            item.update({
                '__plan__': plan,
                '__unit_pk__': unit.pk if unit else None,
                '__unit_code__': unit.code if unit else '',
                '__student_no__': student_no,
                '__name__': name,
                '__status__': status,
                '__enrolled_at__': enrolled_at,
                '__existing_pk__': record.pk if record else None,
            })
            validated.append(item)

        return validated, errors

    # ---------------- 提交 ----------------
    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_organization.models import (
            IMPORT_COMMITTED,
            DataImportJob,
            DataImportRowError,
            OrganizationUnit,
            StudentRecord,
            StudentRecordChange,
        )

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}

        with transaction.atomic():
            job = DataImportJob.objects.create(
                kind=self.dataset[:32],
                total_rows=len(validated),
                created_by=actor,
            )

            for item in validated:
                plan = item.get('__plan__')
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue

                unit = None
                if item.get('__unit_pk__'):
                    unit = OrganizationUnit.objects.filter(pk=item['__unit_pk__']).first()

                defaults = {
                    'name': item['__name__'],
                    'unit': unit,
                    'status': item['__status__'],
                }
                enrolled = item.get('__enrolled_at__')
                if enrolled:
                    defaults['enrolled_at'] = enrolled

                if plan == 'update':
                    record = StudentRecord.objects.select_for_update().filter(
                        pk=item['__existing_pk__']).first()
                    if record is None:
                        # 预检后被删除 -> 记为 conflict 而不是静默新建
                        stats['conflict'] += 1
                        DataImportRowError.objects.create(
                            job=job, row_number=item.get('__row__', 0),
                            column='student_no', error_code='VANISHED',
                            message='预检后该学籍记录已不存在')
                        continue
                    for field_name, new_value in defaults.items():
                        old_value = getattr(record, field_name)
                        if field_name == 'unit':
                            old_cmp = getattr(record, 'unit_id', None)
                            new_cmp = getattr(new_value, 'pk', None)
                        else:
                            old_cmp, new_cmp = old_value, new_value
                        if old_cmp == new_cmp:
                            continue
                        setattr(record, field_name, new_value)
                        StudentRecordChange.objects.create(
                            record=record, field_name=field_name,
                            old_value='' if old_cmp is None else str(old_cmp)[:255],
                            new_value='' if new_cmp is None else str(new_cmp)[:255],
                            changed_by=actor, batch_id=str(job.batch_id),
                        )
                    record.version = (record.version or 1) + 1
                    record.save()
                    stats['updated'] += 1
                else:
                    record = StudentRecord.objects.create(
                        student_no=item['__student_no__'],
                        **defaults,
                    )
                    StudentRecordChange.objects.create(
                        record=record, field_name='*', old_value='',
                        new_value='created', changed_by=actor,
                        batch_id=str(job.batch_id),
                    )
                    stats['created'] += 1

            job.success_rows = stats['created'] + stats['updated'] + stats['skipped']
            job.error_rows = stats['conflict']
            job.status = IMPORT_COMMITTED
            from django.utils import timezone

            job.committed_at = timezone.now()
            job.save(update_fields=['status', 'success_rows', 'error_rows', 'committed_at'])

        return job, stats

    # ---------------- 差异预览 ----------------
    def describe_row(self, row, account):
        out = {
            'row': row.get('__row__', 0),
            'student_no': row.get('__student_no__', ''),
            'name': row.get('__name__', ''),
            'unit_code': row.get('__unit_code__', ''),
            'status': row.get('__status__', ''),
            'plan': row.get('__plan__', ''),
        }
        return out


register_adapter(R4StudentAdapter())
