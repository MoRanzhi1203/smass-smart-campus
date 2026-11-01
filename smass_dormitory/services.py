"""宿舍业务服务：分配、调宿、退宿、报修、巡查、宿管范围。

所有写操作在事务 + 行锁内校验；“同一学生/床位同时只有一条活跃关系”
由 ``active_slot`` 普通唯一约束兜底，服务层负责给出可读错误。
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import (
    Bed,
    DormAssignment,
    DormBuilding,
    DormChangeRequest,
    DormCheckoutRequest,
    DormInspection,
    DormManagerScope,
    DormRepair,
    DormRoom,
)


class DormError(ValueError):
    def __init__(self, message, code='DORM_ERROR'):
        super().__init__(message)
        self.code = code


def _actor_id(actor):
    return str(getattr(actor, 'pk', '') or actor or '')[:32]


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def active_assignment(student):
    return (DormAssignment.objects
            .filter(student=student, active_slot=1)
            .select_related('bed', 'bed__room', 'bed__room__room',
                            'bed__room__building', 'bed__room__building__building')
            .first())


def available_beds(building=None, room=None):
    queryset = (Bed.objects.filter(status=Bed.STATUS_FREE)
                .select_related('room', 'room__room', 'room__building',
                                'room__building__building'))
    if building is not None:
        queryset = queryset.filter(room__building=building)
    if room is not None:
        queryset = queryset.filter(room=room)
    return queryset.order_by('room__building__building__code',
                             'room__room__code', 'number')


def staff_buildings(account):
    """账号被授权的楼栋（主管/楼管/维修）。"""
    if getattr(account, 'pk', None) is None:
        return DormBuilding.objects.none()
    ids = DormManagerScope.objects.filter(
        account=account).values_list('building_id', flat=True)
    return DormBuilding.objects.filter(pk__in=list(ids))


def can_manage_building(account, building):
    if building is None:
        return False
    if getattr(account, 'is_superuser', False):
        return True
    roles = set(getattr(account, 'active_roles', lambda: [])() or [])
    if 'system_admin' in roles:
        return True
    return DormManagerScope.objects.filter(
        account=account, building=building).exists()


def can_manage_room(account, room):
    if room is None:
        return False
    return can_manage_building(account, room.building)


# ---------------------------------------------------------------------------
# 分配
# ---------------------------------------------------------------------------
def allocate(student, bed, actor=None, *, batch_code='', note=''):
    if student is None or bed is None:
        raise DormError('缺少学生或床位')
    with transaction.atomic():
        locked_bed = Bed.objects.select_for_update().get(pk=bed.pk)
        if locked_bed.status != Bed.STATUS_FREE:
            raise DormError('床位不是空闲状态', code='BED_NOT_FREE')
        room = DormRoom.objects.select_for_update().get(pk=locked_bed.room_id)
        if room.status != DormRoom.STATUS_OPEN:
            raise DormError('寝室不可用', code='ROOM_CLOSED')
        building = room.building
        if building.status != DormBuilding.STATUS_OPEN:
            raise DormError('楼栋维护中', code='BUILDING_CLOSED')
        if active_assignment(student) is not None:
            raise DormError('该学生已有在住关系', code='ALREADY_ASSIGNED')
        occupied = DormAssignment.objects.filter(
            bed__room=room, active_slot=1).count()
        if occupied >= room.capacity:
            raise DormError('寝室已满', code='ROOM_FULL')
        assignment = DormAssignment.objects.create(
            student=student, bed=locked_bed, status=DormAssignment.STATUS_ACTIVE,
            active_slot=1, checkin_at=timezone.now(), batch_code=batch_code[:64],
            note=(note or '')[:200])
        locked_bed.status = Bed.STATUS_OCCUPIED
        locked_bed.save(update_fields=['status'])
    return assignment


# ---------------------------------------------------------------------------
# 调宿
# ---------------------------------------------------------------------------
def request_change(student, to_bed, reason, actor=None):
    if not str(reason or '').strip():
        raise DormError('调宿必须填写理由', code='EMPTY_REASON')
    assignment = active_assignment(student)
    return DormChangeRequest.objects.create(
        student=student, from_bed=assignment.bed if assignment else None,
        to_bed=to_bed, reason=str(reason).strip()[:500],
        submitted_by=_actor_id(actor))


def approve_change(request_obj, actor):
    if request_obj.status != DormChangeRequest.STATUS_SUBMITTED:
        raise DormError('只有待审批的调宿可以批准', code='BAD_STATE')
    to_bed = request_obj.to_bed
    if to_bed is None:
        raise DormError('缺少目标床位', code='NO_TARGET_BED')
    with transaction.atomic():
        locked_target = Bed.objects.select_for_update().get(pk=to_bed.pk)
        if locked_target.status != Bed.STATUS_FREE:
            raise DormError('目标床位已被占用', code='TARGET_TAKEN')
        room = DormRoom.objects.select_for_update().get(
            pk=locked_target.room_id)
        if room.status != DormRoom.STATUS_OPEN:
            raise DormError('目标寝室不可用', code='ROOM_CLOSED')
        if room.building.status != DormBuilding.STATUS_OPEN:
            raise DormError('目标楼栋维护中', code='BUILDING_CLOSED')
        assignment = active_assignment(request_obj.student)
        if assignment is None:
            raise DormError('该学生当前没有在住关系', code='NO_ASSIGNMENT')
        old_bed = Bed.objects.select_for_update().get(pk=assignment.bed_id)
        assignment.status = DormAssignment.STATUS_CHECKED_OUT
        assignment.active_slot = None
        assignment.checkout_at = timezone.now()
        assignment.save(update_fields=['status', 'active_slot', 'checkout_at'])
        old_bed.status = Bed.STATUS_FREE
        old_bed.save(update_fields=['status'])
        DormAssignment.objects.create(
            student=request_obj.student, bed=locked_target,
            status=DormAssignment.STATUS_ACTIVE, active_slot=1,
            checkin_at=timezone.now(),
            batch_code=assignment.batch_code, note='调宿')
        locked_target.status = Bed.STATUS_OCCUPIED
        locked_target.save(update_fields=['status'])
        request_obj.status = DormChangeRequest.STATUS_COMPLETED
        request_obj.reviewed_by = _actor_id(actor)
        request_obj.reviewed_at = timezone.now()
        request_obj.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                        'updated_at'])
    return request_obj


def reject_change(request_obj, actor, reason):
    if request_obj.status != DormChangeRequest.STATUS_SUBMITTED:
        raise DormError('只有待审批的调宿可以驳回', code='BAD_STATE')
    if not str(reason or '').strip():
        raise DormError('驳回必须填写原因', code='EMPTY_REASON')
    request_obj.status = DormChangeRequest.STATUS_REJECTED
    request_obj.reviewed_by = _actor_id(actor)
    request_obj.reviewed_at = timezone.now()
    request_obj.reject_reason = str(reason).strip()[:255]
    request_obj.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                    'reject_reason', 'updated_at'])
    return request_obj


# ---------------------------------------------------------------------------
# 退宿
# ---------------------------------------------------------------------------
def request_checkout(student, reason, actor=None):
    if not str(reason or '').strip():
        raise DormError('退宿必须填写原因', code='EMPTY_REASON')
    assignment = active_assignment(student)
    if assignment is None:
        raise DormError('该学生当前没有在住关系', code='NO_ASSIGNMENT')
    return DormCheckoutRequest.objects.create(
        student=student, assignment=assignment,
        reason=str(reason).strip()[:500])


def approve_checkout(request_obj, actor):
    if request_obj.status != DormCheckoutRequest.STATUS_SUBMITTED:
        raise DormError('只有待审批的退宿可以批准', code='BAD_STATE')
    with transaction.atomic():
        assignment = active_assignment(request_obj.student)
        if assignment is None:
            raise DormError('该学生当前没有在住关系', code='NO_ASSIGNMENT')
        bed = Bed.objects.select_for_update().get(pk=assignment.bed_id)
        assignment.status = DormAssignment.STATUS_CHECKED_OUT
        assignment.active_slot = None
        assignment.checkout_at = timezone.now()
        assignment.save(update_fields=['status', 'active_slot', 'checkout_at'])
        bed.status = Bed.STATUS_FREE
        bed.save(update_fields=['status'])
        request_obj.status = DormCheckoutRequest.STATUS_COMPLETED
        request_obj.reviewed_by = _actor_id(actor)
        request_obj.reviewed_at = timezone.now()
        request_obj.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                        'updated_at'])
    return request_obj


# ---------------------------------------------------------------------------
# 报修
# ---------------------------------------------------------------------------
REPAIR_FLOW = {
    DormRepair.STATUS_SUBMITTED: DormRepair.STATUS_ASSIGNED,
    DormRepair.STATUS_ASSIGNED: DormRepair.STATUS_PROCESSING,
    DormRepair.STATUS_PROCESSING: DormRepair.STATUS_DONE,
    DormRepair.STATUS_DONE: DormRepair.STATUS_CLOSED,
}


def create_repair(room, description, actor=None, *, bed=None, student=None):
    if not str(description or '').strip():
        raise DormError('报修必须填写问题描述', code='EMPTY_DESCRIPTION')
    return DormRepair.objects.create(
        room=room, bed=bed, student=student,
        description=str(description).strip()[:500],
        created_by=_actor_id(actor))


def advance_repair(repair, actor, *, assignee=''):
    target = REPAIR_FLOW.get(repair.status)
    if target is None:
        raise DormError('报修单已结束', code='BAD_STATE')
    repair.status = target
    if assignee:
        repair.assignee = assignee[:32]
    if target == DormRepair.STATUS_DONE:
        repair.done_at = timezone.now()
    repair.save(update_fields=['status', 'assignee', 'done_at'])
    return repair


# ---------------------------------------------------------------------------
# 巡查
# ---------------------------------------------------------------------------
def record_inspection(building, *, room=None, items=None, result='ok',
                      issue='', inspector=''):
    if building is None:
        raise DormError('缺少宿舍楼', code='NO_BUILDING')
    if result == DormInspection.RESULT_ISSUE and not str(issue or '').strip():
        raise DormError('登记问题时必须填写问题描述', code='EMPTY_ISSUE')
    return DormInspection.objects.create(
        building=building, room=room, items=items or {}, result=result,
        issue=str(issue or '')[:500], inspector=inspector[:32])


def advance_inspection(inspection, actor=None):
    if inspection.status == DormInspection.STATUS_RECORDED:
        inspection.status = DormInspection.STATUS_RECTIFYING
    elif inspection.status == DormInspection.STATUS_RECTIFYING:
        inspection.status = DormInspection.STATUS_CLOSED
    else:
        raise DormError('巡查记录已关闭', code='BAD_STATE')
    inspection.save(update_fields=['status'])
    return inspection
