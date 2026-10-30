"""R12 服务层：自动分班、转专业与学籍异动。

所有写操作只经本模块，视图不直接改模型。

规则摘要
--------
- 分班：候选 = 在读且尚未编入班级的学籍档案；先预览（不写档案），再执行，
  执行可回滚；每步写 ``StudentRecordChange``。
- 转专业/学籍异动：提交 → 审批 → 生效；审批人不得是提交人（S12 职责分离）。
- 任何非法状态迁移都抛 ``EnrollmentError``，不静默降级。
"""
from __future__ import annotations

import logging
from collections import Counter, OrderedDict

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
    StudentRecordChange,
)

from .models import (
    ASSIGNMENT_APPLIED,
    ASSIGNMENT_ROLLED_BACK,
    CHANGE_APPROVED,
    CHANGE_EFFECTIVE,
    CHANGE_GRADUATE,
    CHANGE_REJECTED,
    CHANGE_RESUME,
    CHANGE_SUBMITTED,
    CHANGE_SUSPEND,
    CHANGE_TRANSFER_OUT,
    CHANGE_TYPES,
    CHANGE_WITHDRAW,
    PLACEMENT_APPLIED,
    PLACEMENT_PREVIEW,
    PLACEMENT_ROLLED_BACK,
    PlacementAssignment,
    PlacementBatch,
    STRATEGY_BALANCED,
    TRANSFER_APPROVED,
    TRANSFER_CANCELLED,
    TRANSFER_EFFECTIVE,
    TRANSFER_REJECTED,
    TRANSFER_SUBMITTED,
    MajorTransferRequest,
    StudentStatusChange,
)

logger = logging.getLogger('smass.audit')

#: 学籍状态机：当前状态 + 异动类型 → 目标状态
STATUS_TRANSITIONS = {
    ('enrolled', CHANGE_SUSPEND): 'suspended',
    ('suspended', CHANGE_RESUME): 'enrolled',
    ('enrolled', CHANGE_WITHDRAW): 'withdrawn',
    ('suspended', CHANGE_WITHDRAW): 'withdrawn',
    ('enrolled', CHANGE_GRADUATE): 'graduated',
    ('enrolled', CHANGE_TRANSFER_OUT): 'withdrawn',
}

#: 终态：不允许再异动
TERMINAL_STATUSES = {'withdrawn', 'graduated'}


class EnrollmentError(ValueError):
    """学籍业务的拒绝。"""

    def __init__(self, message, code='ENROLLMENT_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(EnrollmentError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


# ---------------------------------------------------------------------------
# 权限与查询
# ---------------------------------------------------------------------------
def can_manage(account):
    """教务/管理员：具备 update 或 manage_roles 动作。"""
    return authz.has_action(account, 'update') or authz.has_action(account, 'manage_roles')


def record_for_account(account):
    return StudentRecord.objects.filter(account=account).first()


def _require_manage(account):
    if not can_manage(account):
        raise PermissionDenied('只有教务管理员可以执行该操作')


def classes_of_major(major):
    return OrganizationUnit.objects.filter(
        unit_type=UNIT_TYPE_CLASS, parent=major, status='active').order_by('code')


def major_of_record(record):
    """推断学籍档案的当前专业单元。"""
    if record.unit is None:
        code = (record.extra or {}).get('major_code')
        if code:
            return OrganizationUnit.objects.filter(
                unit_type=UNIT_TYPE_MAJOR, code=code).first()
        return None
    if record.unit.unit_type == UNIT_TYPE_MAJOR:
        return record.unit
    if record.unit.parent is not None and record.unit.parent.unit_type == UNIT_TYPE_MAJOR:
        return record.unit.parent
    code = (record.extra or {}).get('major_code')
    if code:
        return OrganizationUnit.objects.filter(
            unit_type=UNIT_TYPE_MAJOR, code=code).first()
    return None


def is_unplaced(record):
    return record.unit is None or record.unit.unit_type != UNIT_TYPE_CLASS


def candidate_records(rule):
    """分班候选：在读、尚未编班、且属于该专业。"""
    records = StudentRecord.objects.filter(status='enrolled').select_related('unit', 'unit__parent')
    result = []
    for record in records:
        if not is_unplaced(record):
            continue
        major = major_of_record(record)
        if major is None or major.pk != rule.major_id:
            continue
        result.append(record)
    return sorted(result, key=lambda r: r.student_no)


# ---------------------------------------------------------------------------
# 分班
# ---------------------------------------------------------------------------
def _balance_value(record, key):
    value = (record.extra or {}).get(key)
    return '' if value is None else str(value)


def _plan_assignments(rule, classes, records):
    """返回 [(record, class)]；按策略与均衡维度分配。"""
    if not classes:
        raise EnrollmentError('该专业下没有可用班级', code='NO_CLASS')

    capacity = int(rule.capacity_per_class or 0)
    if capacity and len(records) > capacity * len(classes):
        raise EnrollmentError(
            '候选 {} 人超过总容量 {}（{} 班 × {} 人）'.format(
                len(records), capacity * len(classes), len(classes), capacity),
            code='CAPACITY_EXCEEDED',
        )

    if rule.strategy != STRATEGY_BALANCED or not rule.balance_keys:
        ordered = list(records)
        return [(record, classes[idx % len(classes)])
                for idx, record in enumerate(ordered)]

    # 均衡：按维度组合分组，组内轮流进入"该组人数最少"的班
    groups = OrderedDict()
    for record in records:
        sig = tuple(_balance_value(record, key) for key in rule.balance_keys)
        groups.setdefault(sig, []).append(record)

    totals = Counter()
    plan = []
    for _sig, members in groups.items():
        per_class = Counter()
        for record in members:
            best = min(
                classes,
                key=lambda cls: (per_class[cls.pk], totals[cls.pk], cls.code),
            )
            if capacity and totals[best.pk] >= capacity:
                raise EnrollmentError(
                    '班级 {} 已达容量上限 {}'.format(best.code, capacity),
                    code='CAPACITY_EXCEEDED',
                )
            per_class[best.pk] += 1
            totals[best.pk] += 1
            plan.append((record, best))

    # 按班级容量与总人数做最终复核
    for cls, count in totals.items():
        if capacity and count > capacity:
            raise EnrollmentError(
                '班级 {} 分配 {} 人超过容量 {}'.format(cls, count, capacity),
                code='CAPACITY_EXCEEDED',
            )
    return plan


def create_placement_preview(rule, actor):
    """生成分班预览（不修改任何学籍档案）。"""
    _require_manage(actor)
    if not rule.is_active:
        raise EnrollmentError('该分班规则已停用', code='RULE_INACTIVE')

    classes = list(classes_of_major(rule.major))
    records = candidate_records(rule)
    if not records:
        raise EnrollmentError('没有可分班的候选学生', code='NO_CANDIDATE')

    plan = _plan_assignments(rule, classes, records)

    with transaction.atomic():
        batch = PlacementBatch.objects.create(
            rule=rule, status=PLACEMENT_PREVIEW, actor_id=_actor_id(actor))
        PlacementAssignment.objects.bulk_create([
            PlacementAssignment(
                batch=batch, record=record,
                from_unit=record.unit, to_unit=cls, status='planned')
            for record, cls in plan
        ])

    per_class = Counter(cls.code for _record, cls in plan)
    batch.stats = {
        'total': len(plan),
        'per_class': dict(per_class),
        'strategy': rule.strategy,
        'balance_keys': list(rule.balance_keys or []),
    }
    batch.save(update_fields=['stats'])
    logger.info('placement_preview batch=%s rule=%s total=%s actor=%s',
                batch.pk, rule.pk, len(plan), _actor_id(actor))
    return batch


def apply_placement(batch, actor):
    """执行分班：写学籍档案并保留原组织，便于回滚。"""
    _require_manage(actor)
    with transaction.atomic():
        locked = PlacementBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != PLACEMENT_PREVIEW:
            raise EnrollmentError(
                '只有预览状态的分班批次可以执行（当前：{}）'.format(locked.status),
                code='BAD_STATE')

        assignments = list(locked.assignments.select_related('record', 'to_unit'))
        if not assignments:
            raise EnrollmentError('批次没有分班结果', code='EMPTY_BATCH')

        now = timezone.now()
        for assignment in assignments:
            record = StudentRecord.objects.select_for_update().get(pk=assignment.record_id)
            old_unit = record.unit
            record.unit = assignment.to_unit
            record.save(update_fields=['unit', 'updated_at'])
            StudentRecordChange.objects.create(
                record=record, field_name='unit',
                old_value='' if old_unit is None else old_unit.code,
                new_value=assignment.to_unit.code,
                reason='自动分班（批次 {}）'.format(locked.pk),
                changed_by=_actor_id(actor),
                batch_id=str(locked.pk)[:36],
            )
            assignment.status = ASSIGNMENT_APPLIED
            assignment.from_unit = old_unit
            assignment.save(update_fields=['status', 'from_unit'])

        locked.status = PLACEMENT_APPLIED
        locked.applied_at = now
        locked.save(update_fields=['status', 'applied_at'])

    logger.info('placement_applied batch=%s total=%s actor=%s',
                locked.pk, len(assignments), _actor_id(actor))
    return locked


def rollback_placement(batch, actor):
    """回滚分班：仅当学生仍停留在本批次分配的班级时才允许。"""
    _require_manage(actor)
    with transaction.atomic():
        locked = PlacementBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != PLACEMENT_APPLIED:
            raise EnrollmentError(
                '只有已执行的分班批次可以回滚（当前：{}）'.format(locked.status),
                code='BAD_STATE')

        assignments = list(locked.assignments.select_related('record', 'from_unit', 'to_unit'))
        for assignment in assignments:
            record = StudentRecord.objects.select_for_update().get(pk=assignment.record_id)
            if record.unit_id != assignment.to_unit_id:
                raise EnrollmentError(
                    '学生 {} 的班级已被其他操作修改，拒绝回滚以免覆盖'.format(record.student_no),
                    code='CONCURRENT_MODIFICATION')

        now = timezone.now()
        for assignment in assignments:
            record = StudentRecord.objects.select_for_update().get(pk=assignment.record_id)
            old_unit = record.unit
            record.unit = assignment.from_unit
            record.save(update_fields=['unit', 'updated_at'])
            StudentRecordChange.objects.create(
                record=record, field_name='unit',
                old_value='' if old_unit is None else old_unit.code,
                new_value='' if assignment.from_unit is None else assignment.from_unit.code,
                reason='回滚自动分班（批次 {}）'.format(locked.pk),
                changed_by=_actor_id(actor),
                batch_id=str(locked.pk)[:36],
            )
            assignment.status = ASSIGNMENT_ROLLED_BACK
            assignment.save(update_fields=['status'])

        locked.status = PLACEMENT_ROLLED_BACK
        locked.rolled_back_at = now
        locked.save(update_fields=['status', 'rolled_back_at'])

    logger.info('placement_rolled_back batch=%s total=%s actor=%s',
                locked.pk, len(assignments), _actor_id(actor))
    return locked


# ---------------------------------------------------------------------------
# 转专业
# ---------------------------------------------------------------------------
def submit_transfer(record, to_major, reason, actor, target_class=None):
    """提交转专业申请（学生本人或教务代提交）。"""
    if not record:
        raise EnrollmentError('学籍档案不存在', code='NO_RECORD')
    is_owner = _is_self(actor, getattr(record.account, 'pk', None))
    if not is_owner:
        _require_manage(actor)
    if to_major is None or to_major.unit_type != UNIT_TYPE_MAJOR:
        raise EnrollmentError('目标专业不合法', code='BAD_MAJOR')
    current_major = major_of_record(record)
    if current_major is not None and current_major.pk == to_major.pk:
        raise EnrollmentError('目标专业与当前专业相同', code='SAME_MAJOR')
    if record.status in TERMINAL_STATUSES:
        raise EnrollmentError('已离校学生不能转专业', code='TERMINAL_STATUS')
    if not str(reason or '').strip():
        raise EnrollmentError('转专业必须填写理由', code='EMPTY_REASON')
    if target_class is not None and target_class.parent_id != to_major.pk:
        raise EnrollmentError('目标班级不属于目标专业', code='BAD_CLASS')

    # MySQL 不支持条件唯一约束（models.W036），因此"一人同时只能有一条进行中申请"
    # 由服务层在行锁内保证，避免并发双提交。
    with transaction.atomic():
        locked = StudentRecord.objects.select_for_update().get(pk=record.pk)
        if MajorTransferRequest.objects.filter(
                record=locked,
                status__in=[TRANSFER_SUBMITTED, TRANSFER_APPROVED]).exists():
            raise EnrollmentError('该学生已有进行中的转专业申请', code='DUPLICATE_REQUEST')

        request = MajorTransferRequest.objects.create(
            record=locked,
            from_unit=locked.unit,
            to_major=to_major,
            target_class=target_class,
            reason=str(reason).strip()[:500],
            submitted_by=_actor_id(actor),
            status=TRANSFER_SUBMITTED,
        )
    logger.info('major_transfer_submitted id=%s record=%s to=%s actor=%s',
                request.pk, record.student_no, to_major.code, _actor_id(actor))
    return request


def approve_transfer(request, actor, *, target_class=None):
    """审批通过（不得自批）。"""
    _require_manage(actor)
    if request.status != TRANSFER_SUBMITTED:
        raise EnrollmentError(
            '只有待审批的申请可以批准（当前：{}）'.format(request.status),
            code='BAD_STATE')
    if _is_self(actor, request.submitted_by):
        raise EnrollmentError('不能审批自己提交的申请（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    if target_class is not None and target_class.parent_id != request.to_major_id:
        raise EnrollmentError('目标班级不属于目标专业', code='BAD_CLASS')

    request.status = TRANSFER_APPROVED
    request.reviewed_by = _actor_id(actor)
    request.reviewed_at = timezone.now()
    if target_class is not None:
        request.target_class = target_class
    request.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'target_class', 'updated_at'])
    logger.info('major_transfer_approved id=%s by=%s', request.pk, _actor_id(actor))
    return request


def reject_transfer(request, actor, reason):
    _require_manage(actor)
    if request.status != TRANSFER_SUBMITTED:
        raise EnrollmentError('只有待审批的申请可以驳回', code='BAD_STATE')
    if _is_self(actor, request.submitted_by):
        raise EnrollmentError('不能驳回自己提交的申请（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise EnrollmentError('驳回必须填写原因', code='EMPTY_REASON')

    request.status = TRANSFER_REJECTED
    request.reviewed_by = _actor_id(actor)
    request.reviewed_at = timezone.now()
    request.reject_reason = str(reason).strip()[:255]
    request.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'reject_reason', 'updated_at'])
    logger.info('major_transfer_rejected id=%s by=%s', request.pk, _actor_id(actor))
    return request


def cancel_transfer(request, actor):
    if request.status != TRANSFER_SUBMITTED:
        raise EnrollmentError('只有待审批的申请可以撤销', code='BAD_STATE')
    if not _is_self(actor, request.submitted_by) and not can_manage(actor):
        raise PermissionDenied()
    request.status = TRANSFER_CANCELLED
    request.save(update_fields=['status', 'updated_at'])
    logger.info('major_transfer_cancelled id=%s by=%s', request.pk, _actor_id(actor))
    return request


def apply_transfer(request, actor, target_class):
    """生效：编入目标班级并写档案变更历史。"""
    _require_manage(actor)
    if request.status != TRANSFER_APPROVED:
        raise EnrollmentError(
            '只有已批准的申请可以生效（当前：{}）'.format(request.status),
            code='BAD_STATE')
    if target_class is None or target_class.unit_type != UNIT_TYPE_CLASS:
        raise EnrollmentError('生效必须指定目标班级', code='NO_TARGET_CLASS')
    if target_class.parent_id != request.to_major_id:
        raise EnrollmentError('目标班级不属于目标专业', code='BAD_CLASS')

    with transaction.atomic():
        record = StudentRecord.objects.select_for_update().get(pk=request.record_id)
        if record.status in TERMINAL_STATUSES:
            raise EnrollmentError('已离校学生不能转专业', code='TERMINAL_STATUS')

        old_unit = record.unit
        old_major = major_of_record(record)
        record.unit = target_class
        record.save(update_fields=['unit', 'updated_at'])
        StudentRecordChange.objects.create(
            record=record, field_name='unit',
            old_value='' if old_unit is None else old_unit.code,
            new_value=target_class.code,
            reason='转专业生效（申请 {}）'.format(request.pk),
            changed_by=_actor_id(actor),
            batch_id=str(request.pk)[:36],
        )
        if old_major is not None and old_major.pk != request.to_major_id:
            StudentRecordChange.objects.create(
                record=record, field_name='major',
                old_value=old_major.code,
                new_value=request.to_major.code,
                reason='转专业生效（申请 {}）'.format(request.pk),
                changed_by=_actor_id(actor),
                batch_id=str(request.pk)[:36],
            )

        request.target_class = target_class
        request.status = TRANSFER_EFFECTIVE
        request.effective_at = timezone.now()
        request.save(update_fields=[
            'target_class', 'status', 'effective_at', 'updated_at'])

    logger.info('major_transfer_effective id=%s record=%s class=%s by=%s',
                request.pk, record.student_no, target_class.code, _actor_id(actor))
    return request


# ---------------------------------------------------------------------------
# 学籍异动
# ---------------------------------------------------------------------------
def submit_status_change(record, change_type, reason, actor,
                         effective_date=None):
    """提交学籍异动申请。

    状态机校验、重复申请检查与写入都在 ``select_for_update`` 行锁内完成，
    因此并发提交同一学生的两个异动时，后到者一定看到前者的进行中记录。
    """
    if not record:
        raise EnrollmentError('学籍档案不存在', code='NO_RECORD')
    if change_type not in dict(CHANGE_TYPES):
        raise EnrollmentError('未知的异动类型', code='BAD_CHANGE_TYPE')
    is_owner = _is_self(actor, getattr(record.account, 'pk', None))
    if not is_owner:
        _require_manage(actor)
    if change_type in (CHANGE_WITHDRAW, CHANGE_GRADUATE, CHANGE_TRANSFER_OUT):
        if not str(reason or '').strip():
            raise EnrollmentError('离校类异动必须填写原因', code='EMPTY_REASON')

    with transaction.atomic():
        locked = StudentRecord.objects.select_for_update().get(pk=record.pk)
        if locked.status in TERMINAL_STATUSES:
            raise EnrollmentError('学生已离校，不能再异动', code='TERMINAL_STATUS')
        key = (locked.status, change_type)
        if key not in STATUS_TRANSITIONS:
            raise EnrollmentError(
                '当前学籍状态 {} 不允许执行 {}'.format(
                    locked.get_status_display(), dict(CHANGE_TYPES)[change_type]),
                code='ILLEGAL_TRANSITION')
        if StudentStatusChange.objects.filter(
                record=locked,
                status__in=[CHANGE_SUBMITTED, CHANGE_APPROVED]).exists():
            raise EnrollmentError('该学生已有进行中的学籍异动', code='DUPLICATE_REQUEST')

        change = StudentStatusChange.objects.create(
            record=locked,
            change_type=change_type,
            from_status=locked.status,
            to_status=STATUS_TRANSITIONS[key],
            effective_date=effective_date,
            reason=str(reason or '').strip()[:500],
            submitted_by=_actor_id(actor),
            status=CHANGE_SUBMITTED,
        )
    logger.info('status_change_submitted id=%s record=%s type=%s actor=%s',
                change.pk, record.student_no, change_type, _actor_id(actor))
    return change


def approve_status_change(change, actor):
    _require_manage(actor)
    if change.status != CHANGE_SUBMITTED:
        raise EnrollmentError('只有待审批的异动可以批准', code='BAD_STATE')
    if _is_self(actor, change.submitted_by):
        raise EnrollmentError('不能审批自己提交的异动（职责分离）',
                              code='SELF_APPROVAL_DENIED')

    change.status = CHANGE_APPROVED
    change.reviewed_by = _actor_id(actor)
    change.reviewed_at = timezone.now()
    change.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
    logger.info('status_change_approved id=%s by=%s', change.pk, _actor_id(actor))
    return change


def reject_status_change(change, actor, reason):
    _require_manage(actor)
    if change.status != CHANGE_SUBMITTED:
        raise EnrollmentError('只有待审批的异动可以驳回', code='BAD_STATE')
    if _is_self(actor, change.submitted_by):
        raise EnrollmentError('不能驳回自己提交的异动（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise EnrollmentError('驳回必须填写原因', code='EMPTY_REASON')

    change.status = CHANGE_REJECTED
    change.reviewed_by = _actor_id(actor)
    change.reviewed_at = timezone.now()
    change.reject_reason = str(reason).strip()[:255]
    change.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'reject_reason', 'updated_at'])
    logger.info('status_change_rejected id=%s by=%s', change.pk, _actor_id(actor))
    return change


def apply_status_change(change, actor):
    """生效：更新学籍状态并写变更历史。"""
    _require_manage(actor)
    if change.status != CHANGE_APPROVED:
        raise EnrollmentError('只有已批准的异动可以生效', code='BAD_STATE')

    with transaction.atomic():
        record = StudentRecord.objects.select_for_update().get(pk=change.record_id)
        expected = STATUS_TRANSITIONS.get((record.status, change.change_type))
        if expected is None:
            raise EnrollmentError(
                '审批后学籍状态已变化（当前 {}），拒绝生效'.format(record.status),
                code='CONCURRENT_MODIFICATION')

        old_status = record.status
        record.status = expected
        record.save(update_fields=['status', 'updated_at'])
        StudentRecordChange.objects.create(
            record=record, field_name='status',
            old_value=old_status, new_value=expected,
            reason='学籍异动生效（{}）'.format(change.get_change_type_display()),
            changed_by=_actor_id(actor),
            batch_id=str(change.pk)[:36],
        )
        change.status = CHANGE_EFFECTIVE
        change.effective_at = timezone.now()
        change.save(update_fields=['status', 'effective_at', 'updated_at'])

    logger.info('status_change_effective id=%s record=%s %s->%s by=%s',
                change.pk, record.student_no, old_status, expected, _actor_id(actor))
    return change


# ---------------------------------------------------------------------------
# 查询视图
# ---------------------------------------------------------------------------
def scoped_transfers(account):
    """按角色收窄的转专业列表（默认拒绝）。"""
    qs = MajorTransferRequest.objects.select_related(
        'record', 'from_unit', 'to_major', 'target_class')
    if can_manage(account):
        return qs
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def scoped_status_changes(account):
    qs = StudentStatusChange.objects.select_related('record')
    if can_manage(account):
        return qs
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def placement_summary(rule):
    """规则当前可预览的规模（用于页面展示）。"""
    classes = list(classes_of_major(rule.major))
    records = candidate_records(rule)
    return {
        'rule': rule,
        'classes': classes,
        'candidates': len(records),
        'capacity_total': (int(rule.capacity_per_class or 0) * len(classes)) or None,
        'existing_students': StudentRecord.objects.filter(
            unit__in=classes).count() if classes else 0,
    }


def batch_rows(batch):
    return list(batch.assignments.select_related(
        'record', 'from_unit', 'to_unit').order_by('to_unit__code', 'record__student_no'))


def status_counts():
    return dict(Counter(
        MajorTransferRequest.objects.values_list('status', flat=True)))
