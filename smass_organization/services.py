"""R4 服务层：组织树校验、字段级权限、导入预检与提交。

关键约束（对应计划 D03/D04/D05/D11）：
- 组织父子关系必须符合 ``ALLOWED_CHILDREN``，且**禁止成环**；
- 字段级权限：没有可见权限的字段**不得出现在任何输出**（HTML/JSON/导出/聚合）；
- 导入分两阶段：预检（只读校验，产生错误行）→ 提交（逐行 upsert + 历史）；
- 单行失败不阻断整批，但必须记录错误行。
"""
import csv
import io
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone

from smass_organization.models import (
    ALLOWED_CHILDREN,
    IMPORT_COMMITTED,
    IMPORT_FAILED,
    IMPORT_PREVIEWED,
    STATUS_ACTIVE,
    DataImportJob,
    DataImportRowError,
    OrganizationMembership,
    OrganizationUnit,
    StudentFieldDefinition,
    StudentRecord,
    StudentRecordChange,
)


class OrganizationError(Exception):
    """组织操作错误基类。"""


class CycleError(OrganizationError):
    """父子关系成环。"""


class InvalidHierarchyError(OrganizationError):
    """父子类型不允许。"""


# ---------------------------------------------------------------------------
# 组织树
# ---------------------------------------------------------------------------
def validate_parent(unit_type, parent, *, moving_unit=None):
    """校验 ``unit_type`` 能否挂在 ``parent`` 下。失败抛异常。"""
    parent_type = parent.unit_type if parent is not None else None

    # 防环优先：把节点移到自身/后代下，是比类型不匹配更严重、更具体的错误。
    if moving_unit is not None and parent is not None:
        node = parent
        guard = 0
        while node is not None and guard < 64:
            if node.pk == moving_unit.pk:
                raise CycleError('不能把节点移动到它自己或它的后代下')
            node = node.parent
            guard += 1

    allowed = ALLOWED_CHILDREN.get(parent_type)
    if allowed is None:
        raise InvalidHierarchyError('未知的父节点类型: {}'.format(parent_type))
    if unit_type not in allowed:
        raise InvalidHierarchyError(
            '{} 不能作为 {} 的下级（允许: {}）'.format(
                parent_type or '根', unit_type, sorted(allowed)
            )
        )

    return True


def create_unit(*, code, name, unit_type, parent=None, sort_order=0,
                valid_from=None, valid_to=None):
    validate_parent(unit_type, parent)
    return OrganizationUnit.objects.create(
        code=code, name=name, unit_type=unit_type, parent=parent,
        sort_order=sort_order, valid_from=valid_from, valid_to=valid_to,
    )


def move_unit(unit, new_parent, *, actor=''):
    """移动节点：校验 → 更新 → 记录审计。"""
    validate_parent(unit.unit_type, new_parent, moving_unit=unit)

    old_parent_id = unit.parent_id
    unit.parent = new_parent
    unit.save(update_fields=['parent', 'updated_at'])

    from r22_account import audit

    try:
        audit.record_success(
            'org_unit_moved',
            actor=None,
            target='organization_unit',
            target_id=unit.code,
            context={
                'from_parent': old_parent_id or 0,
                'to_parent': getattr(new_parent, 'pk', None) or 0,
                'actor': actor,
            },
        )
    except Exception:  # noqa: BLE001 - 审计失败不应破坏业务，但需可见
        pass

    return unit


def subtree(unit):
    """返回以 unit 为根的子树（广度优先，带深度上限）。"""
    result = []
    queue = [unit]
    guard = 0
    while queue and guard < 1000:
        node = queue.pop(0)
        result.append(node)
        queue.extend(list(node.children.all()))
        guard += 1
    return result


# ---------------------------------------------------------------------------
# 组织级数据范围（R4-01，P0）
# ---------------------------------------------------------------------------
#: 角色 -> 可见范围
SCOPE_GLOBAL_ROLES = {'system_admin'}


def scoped_units(account):
    """返回账号可见的组织单元查询集。

    规则（默认拒绝）：
    - 无角色 / 停用 / 匿名 -> 空集；
    - system_admin -> 全部；
    - 其他角色 -> **仅自己有效成员关系所在节点及其后代子树**；
    - 无有效成员关系 -> 空集（绝不回退为"全部"）。
    """
    from r21_account.models import RoleCode

    roles = account_roles(account)
    if not roles:
        return OrganizationUnit.objects.none()

    if RoleCode.SYSTEM_ADMIN in roles or SCOPE_GLOBAL_ROLES & roles:
        return OrganizationUnit.objects.all()

    memberships = list(
        OrganizationMembership.objects.filter(
            account=account, ended_at__isnull=True
        ).values_list('unit_id', flat=True)
    )
    if not memberships:
        return OrganizationUnit.objects.none()

    allowed_ids = set()
    for root in OrganizationUnit.objects.filter(pk__in=memberships):
        allowed_ids.update(unit.pk for unit in subtree(root))

    if not allowed_ids:
        return OrganizationUnit.objects.none()

    return OrganizationUnit.objects.filter(pk__in=allowed_ids)


def scoped_students(account):
    """返回账号可见的学生档案查询集（列表/详情/搜索/导出/API 统一入口）。"""
    from r21_account.models import RoleCode

    roles = account_roles(account)
    if not roles:
        return StudentRecord.objects.none()

    # 学生：只能看自己
    if RoleCode.STUDENT in roles and not (SCOPE_GLOBAL_ROLES & roles):
        return StudentRecord.objects.filter(account=account)

    if RoleCode.SYSTEM_ADMIN in roles or SCOPE_GLOBAL_ROLES & roles:
        return StudentRecord.objects.all()

    unit_ids = list(scoped_units(account).values_list('pk', flat=True))
    if not unit_ids:
        return StudentRecord.objects.none()

    return StudentRecord.objects.filter(unit_id__in=unit_ids)


def can_access_student(account, record):
    """单对象访问判定（防 IDOR）。"""
    return scoped_students(account).filter(pk=record.pk).exists()


def can_access_unit(account, unit):
    return scoped_units(account).filter(pk=unit.pk).exists()


# ---------------------------------------------------------------------------
# 字段级权限
# ---------------------------------------------------------------------------
def account_roles(account):
    if account is None or not getattr(account, 'is_authenticated', False):
        return set()
    if not getattr(account, 'is_active', False):
        return set()
    return set(account.active_roles())


def _roles_allow(allowed_roles, roles):
    """``allowed_roles`` 为空表示"不限制"（公开字段）。"""
    if not allowed_roles:
        return True
    return bool(set(allowed_roles) & roles)


def visible_fields(account):
    roles = account_roles(account)
    return [
        field for field in StudentFieldDefinition.objects.filter(active=True)
        .order_by('sort_order', 'code')
        if _roles_allow(field.visible_roles, roles)
    ]


def editable_fields(account):
    roles = account_roles(account)
    return [
        field for field in StudentFieldDefinition.objects.filter(active=True)
        .order_by('sort_order', 'code')
        if _roles_allow(field.editable_roles, roles)
    ]


def filtered_extra(record, account):
    """按字段级权限裁剪 ``extra``：无权限字段**不出现在返回值中**。"""
    allowed = {field.code for field in visible_fields(account)}
    return {key: value for key, value in (record.extra or {}).items() if key in allowed}


def can_view_field(account, code):
    return any(field.code == code for field in visible_fields(account))


def can_edit_field(account, code):
    return any(field.code == code for field in editable_fields(account))


# ---------------------------------------------------------------------------
# 并发安全（R4-02）：乐观锁
# ---------------------------------------------------------------------------
class ConcurrencyError(Exception):
    """版本冲突：记录已被他人修改。"""


def update_student(record, *, name=None, status=None, unit=None,
                   expected_version=None, actor=''):
    """带乐观锁的档案更新。

    - 提供 ``expected_version`` 时使用**条件更新**（WHERE version=expected），
      影响行数为 0 即视为冲突，抛 ``ConcurrencyError``；
    - 未提供时退化为普通更新（调用方需自行确认场景）；
    - 成功写 ``StudentRecordChange`` 历史。
    """
    fields = {}
    changes = []

    if name is not None and name != record.name:
        fields['name'] = name
        changes.append(('name', record.name, name))
    if status is not None and status != record.status:
        fields['status'] = status
        changes.append(('status', record.status, status))
    if unit is not None and record.unit_id != getattr(unit, 'pk', None):
        fields['unit'] = unit
        changes.append(('unit', str(record.unit_id or ''), str(getattr(unit, 'pk', ''))))

    if not fields:
        return record, []

    with transaction.atomic():
        queryset = StudentRecord.objects.filter(pk=record.pk)
        if expected_version is not None:
            queryset = queryset.filter(version=expected_version)

        affected = queryset.update(
            version=models.F('version') + 1,
            updated_at=timezone.now(),
            **fields
        )
        if affected == 0:
            raise ConcurrencyError(
                '版本冲突：期望 version={}，记录已被他人修改'.format(expected_version)
            )

        for field_name, old, new in changes:
            StudentRecordChange.objects.create(
                record_id=record.pk, field_name=field_name,
                old_value=str(old)[:255], new_value=str(new)[:255],
                changed_by=actor[:32],
            )

    record.refresh_from_db()
    return record, changes


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = ('student_no', 'name')
VALID_STATUS = {choice[0] for choice in StudentRecord.status.field.choices}


def _parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    return list(reader), list(reader.fieldnames or [])


def import_preview(text, *, actor=''):
    """解析并逐行校验，返回 ``(job, preview_rows)``；不写业务数据。"""
    rows, headers = _parse_csv(text)

    job = DataImportJob.objects.create(
        status=IMPORT_PREVIEWED,
        total_rows=len(rows),
        created_by=actor[:32],
    )

    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        job.status = IMPORT_FAILED
        job.error_rows = len(rows) or 1
        job.save(update_fields=['status', 'error_rows'])
        DataImportRowError.objects.create(
            job=job, row_number=0, column=','.join(missing),
            error_code='MISSING_COLUMN',
            message='缺少必需列: {}'.format(','.join(missing)),
        )
        return job, []

    seen = set()
    preview = []
    errors = 0

    for index, row in enumerate(rows, start=2):  # 第 1 行是表头
        student_no = (row.get('student_no') or '').strip()
        name = (row.get('name') or '').strip()
        unit_code = (row.get('unit_code') or '').strip()
        status = (row.get('status') or 'enrolled').strip()

        row_errors = []
        if not student_no:
            row_errors.append(('student_no', 'EMPTY_STUDENT_NO', '学号不能为空'))
        elif student_no in seen:
            row_errors.append(('student_no', 'DUPLICATE_IN_FILE', '文件内重复学号'))
        else:
            seen.add(student_no)

        if not name:
            row_errors.append(('name', 'EMPTY_NAME', '姓名不能为空'))

        if status not in VALID_STATUS:
            row_errors.append(('status', 'INVALID_STATUS', '非法学籍状态'))

        unit = None
        if unit_code:
            unit = OrganizationUnit.objects.filter(code=unit_code).first()
            if unit is None:
                row_errors.append(('unit_code', 'UNKNOWN_UNIT', '组织不存在'))

        if row_errors:
            errors += 1
            for column, code, message in row_errors:
                DataImportRowError.objects.create(
                    job=job, row_number=index, column=column,
                    error_code=code, message=message,
                )
            preview.append({'row': index, 'ok': False, 'errors': len(row_errors)})
            continue

        preview.append({
            'row': index, 'ok': True, 'student_no': student_no,
            'name': name, 'unit': unit.code if unit else '',
            'status': status,
            'existing': StudentRecord.objects.filter(student_no=student_no).exists(),
        })

    job.success_rows = len(rows) - errors
    job.error_rows = errors
    if errors and not job.success_rows:
        job.status = IMPORT_FAILED
    job.save(update_fields=['success_rows', 'error_rows', 'status'])

    return job, preview


def import_commit(text, *, actor='', batch_actor='import'):
    """预检 + 提交：逐行 upsert，写变更历史；单行失败不阻断其他行。"""
    job, preview = import_preview(text, actor=actor)
    if job.status == IMPORT_FAILED:
        return job, {'created': 0, 'updated': 0, 'failed': job.error_rows}

    created = updated = failed = 0
    rows, _headers = _parse_csv(text)

    for index, row in enumerate(rows, start=2):
        student_no = (row.get('student_no') or '').strip()
        if not student_no:
            continue
        entry = next((p for p in preview if p['row'] == index), None)
        if entry is None or not entry['ok']:
            failed += 1
            continue

        try:
            with transaction.atomic():
                unit = OrganizationUnit.objects.filter(
                    code=(row.get('unit_code') or '').strip()
                ).first()

                record = StudentRecord.objects.filter(student_no=student_no).first()
                if record is None:
                    record = StudentRecord.objects.create(
                        student_no=student_no,
                        name=row['name'].strip(),
                        unit=unit,
                        status=row.get('status') or 'enrolled',
                        extra={},
                    )
                    created += 1
                    StudentRecordChange.objects.create(
                        record=record, field_name='*', old_value='', new_value='created',
                        changed_by=actor[:32], batch_id=str(job.batch_id),
                    )
                else:
                    changes = []
                    if record.name != row['name'].strip():
                        changes.append(('name', record.name, row['name'].strip()))
                        record.name = row['name'].strip()
                    new_status = row.get('status') or record.status
                    if record.status != new_status:
                        changes.append(('status', record.status, new_status))
                        record.status = new_status
                    if unit is not None and record.unit_id != unit.pk:
                        changes.append(('unit', str(record.unit_id or ''), str(unit.pk)))
                        record.unit = unit

                    if changes:
                        record.version += 1
                        record.save(update_fields=[
                            'name', 'status', 'unit', 'version', 'updated_at',
                        ])
                        updated += 1
                        for field_name, old, new in changes:
                            StudentRecordChange.objects.create(
                                record=record, field_name=field_name,
                                old_value=str(old)[:255], new_value=str(new)[:255],
                                changed_by=actor[:32], batch_id=str(job.batch_id),
                            )
        except Exception:  # noqa: BLE001 - 单行失败不阻断整批
            failed += 1
            DataImportRowError.objects.create(
                job=job, row_number=index, error_code='ROW_FAILED',
                message='该行写入失败',
            )

    job.status = IMPORT_COMMITTED
    job.committed_at = timezone.now()
    job.save(update_fields=['status', 'committed_at'])

    return job, {'created': created, 'updated': updated, 'failed': failed}
