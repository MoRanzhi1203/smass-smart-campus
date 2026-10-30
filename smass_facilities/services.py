"""R16 服务层：可用性、冲突检测、预约生命周期。

核心规则（对应主任务书 R16）：
- **不允许时间重叠**：同一房间的占用区间必须互斥；
- **维护封闭期**内不允许预约；
- 房间状态非 ``open`` 不允许预约；
- 需要资格的房间，账号必须有未过期的 ``RoomQualification``；
- 需要审批的房间，预约先进入 ``pending``，批准后才算占用生效；
- 容量不足（``attendees > capacity``，capacity>0 时）拒绝；
- 签到 / 爽约 / 释放形成可审计的状态迁移；
- 所有写操作走本模块，视图不直接改模型。

并发处理
--------
MySQL 的 CHECK 无法表达"区间不重叠"，因此在事务里先
``Room.objects.select_for_update()`` 锁住房间行，再查询冲突；
同一房间的预约请求因此串行化，避免两个并发请求都通过检查。
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from r21_account import authorization as authz

from .models import (
    BOOKING_APPROVED,
    BOOKING_CANCELLED,
    BOOKING_CHECKED_IN,
    BOOKING_NO_SHOW,
    BOOKING_PENDING,
    BOOKING_REJECTED,
    BOOKING_RELEASED,
    OCCUPYING_STATUSES,
    ROOM_STATUS_OPEN,
    Room,
    RoomAvailability,
    RoomBooking,
    RoomQualification,
    MaintenanceWindow,
)

logger = logging.getLogger('smass.audit')


class FacilityError(ValueError):
    """场地业务的拒绝。"""

    def __init__(self, message, code='FACILITY_ERROR'):
        self.code = code
        super().__init__(message)


class BookingConflict(FacilityError):
    def __init__(self, message, conflicts=()):
        super().__init__(message, code='BOOKING_CONFLICT')
        self.conflicts = list(conflicts)


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


# ---------------------------------------------------------------------------
# 查询：冲突 / 封闭期 / 可用时段
# ---------------------------------------------------------------------------
def find_conflicts(room, start_at, end_at, *, exclude_id=None):
    """返回与该区间重叠的占用中预约。"""
    if end_at <= start_at:
        raise FacilityError('结束时间必须晚于开始时间', code='BAD_RANGE')
    qs = RoomBooking.objects.filter(
        room=room,
        status__in=OCCUPYING_STATUSES,
        start_at__lt=end_at,
        end_at__gt=start_at,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return list(qs.order_by('start_at'))


def find_maintenance(room, start_at, end_at):
    """返回与该区间重叠的维护封闭期。"""
    return list(MaintenanceWindow.objects.filter(
        room=room,
        start_at__lt=end_at,
        end_at__gt=start_at,
    ).order_by('start_at'))


def availability_windows(room):
    """房间的常规可用时段（周内）。"""
    return list(RoomAvailability.objects.filter(room=room).order_by('weekday', 'start_time'))


def is_within_availability(room, start_at, end_at):
    """区间是否完全落在某个常规可用时段内。

    房间若**没有**配置任何可用时段，视为"全天可用"（避免必须逐间配置才能用）。
    """
    windows = availability_windows(room)
    if not windows:
        return True
    local_start = timezone.localtime(start_at)
    local_end = timezone.localtime(end_at)
    if local_start.date() != local_end.date():
        # 跨天预约不按周内时段判断（交由审批人决定）
        return True
    weekday = local_start.weekday()
    start_t = local_start.time()
    end_t = local_end.time()
    for w in windows:
        if w.weekday != weekday:
            continue
        if w.start_time <= start_t and end_t <= w.end_time:
            return True
    return False


def has_qualification(account, room, *, at=None):
    if not room.requires_qualification:
        return True
    at = at or timezone.now()
    qs = RoomQualification.objects.filter(room=room, account=account)
    qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))
    return qs.exists()


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def can_book(account, room):
    """是否具备预约资格（不含时间冲突判断）。

    预约是**普通用户**操作，因此只要求"有有效角色"，不要求
    ``add_data`` 这类管理权限；审批才需要 ``update``。
    """
    if not authz.active_roles(account):
        return False
    if not room.bookable:
        return False
    return has_qualification(account, room)


def can_approve(account):
    return authz.has_action(account, 'update')


def can_manage_rooms(account):
    return authz.has_action(account, 'manage_roles')


# ---------------------------------------------------------------------------
# 预约生命周期
# ---------------------------------------------------------------------------
def create_booking(account, room, start_at, end_at, purpose, *,
                   attendees=0, request=None):
    """创建预约。

    校验顺序（任一失败即拒绝，不写库）：
    1. 时间区间合法；
    2. 账号有 ``create`` 权限且房间可预约；
    3. 房间需要资格时账号有未过期资格；
    4. 容量足够（``capacity > 0`` 时 ``attendees <= capacity``）；
    5. 区间落在常规可用时段内；
    6. 无维护封闭期重叠；
    7. 无其它占用预约重叠。
    """
    if not purpose or not str(purpose).strip():
        raise FacilityError('用途不能为空', code='EMPTY_PURPOSE')
    if end_at <= start_at:
        raise FacilityError('结束时间必须晚于开始时间', code='BAD_RANGE')
    if start_at < timezone.now() - timezone.timedelta(minutes=5):
        raise FacilityError('不能预约过去的时间', code='PAST_TIME')

    if not authz.active_roles(account):
        raise FacilityError('当前账号没有预约权限', code='PERMISSION_DENIED')
    if not room.bookable:
        raise FacilityError('房间当前不可预约（状态：{}）'.format(room.status),
                            code='ROOM_NOT_BOOKABLE')
    if not has_qualification(account, room):
        raise FacilityError('缺少该房间的使用资格', code='QUALIFICATION_REQUIRED')

    attendees = int(attendees or 0)
    if attendees < 0:
        raise FacilityError('人数不能为负', code='BAD_ATTENDEES')
    if room.capacity and attendees > room.capacity:
        raise FacilityError(
            '人数 {} 超过房间容量 {}'.format(attendees, room.capacity),
            code='CAPACITY_EXCEEDED')

    if not is_within_availability(room, start_at, end_at):
        raise FacilityError('该时段不在房间的可用时间内', code='OUT_OF_AVAILABILITY')

    with transaction.atomic():
        # 锁住房间行，使同一房间的并发预约串行化
        locked_room = Room.objects.select_for_update().get(pk=room.pk)

        maintenance = find_maintenance(locked_room, start_at, end_at)
        if maintenance:
            raise FacilityError(
                '该时段处于维护封闭期（{}）'.format(maintenance[0].reason or '维护'),
                code='MAINTENANCE_WINDOW')

        conflicts = find_conflicts(locked_room, start_at, end_at)
        if conflicts:
            raise BookingConflict(
                '该时段已被占用（{} 条冲突）'.format(len(conflicts)),
                conflicts=conflicts)

        status = BOOKING_PENDING if locked_room.requires_approval else BOOKING_APPROVED
        booking = RoomBooking.objects.create(
            room=locked_room,
            account=account,
            purpose=str(purpose).strip()[:200],
            start_at=start_at,
            end_at=end_at,
            attendees=attendees,
            status=status,
            approved_by='' if status == BOOKING_PENDING else 'auto',
            approved_at=None if status == BOOKING_PENDING else timezone.now(),
        )

    logger.info('room_booking_created id=%s room=%s account=%s status=%s',
                booking.pk, room.pk, _actor_id(account), booking.status)
    return booking


def approve_booking(booking, actor, *, request=None):
    """审批通过。仅 pending 可批。"""
    if booking.status != BOOKING_PENDING:
        raise FacilityError('只有待审批的预约可以批准（当前：{}）'.format(booking.status),
                            code='BAD_STATE')
    if not can_approve(actor):
        raise FacilityError('当前账号没有审批权限', code='PERMISSION_DENIED')
    if str(getattr(booking.account, 'pk', '')) == str(getattr(actor, 'pk', '')):
        # 职责分离：不允许自批（与 S12 一致）
        raise FacilityError('不能审批自己提交的预约', code='SELF_APPROVAL_DENIED')

    with transaction.atomic():
        Room.objects.select_for_update().get(pk=booking.room_id)
        conflicts = find_conflicts(booking.room, booking.start_at, booking.end_at,
                                   exclude_id=booking.pk)
        if conflicts:
            raise BookingConflict('批准前复核发现冲突', conflicts=conflicts)
        booking.status = BOOKING_APPROVED
        booking.approved_by = _actor_id(actor)
        booking.approved_at = timezone.now()
        booking.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    logger.info('room_booking_approved id=%s by=%s', booking.pk, _actor_id(actor))
    return booking


def reject_booking(booking, actor, reason='', *, request=None):
    """驳回待审批预约（必须填写原因，且不得自批）。"""
    if booking.status != BOOKING_PENDING:
        raise FacilityError('只有待审批的预约可以驳回', code='BAD_STATE')
    if not can_approve(actor):
        raise FacilityError('当前账号没有审批权限', code='PERMISSION_DENIED')
    if str(getattr(booking.account, 'pk', '')) == str(getattr(actor, 'pk', '')):
        raise FacilityError('不能驳回自己提交的预约', code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise FacilityError('驳回必须填写原因', code='EMPTY_REASON')

    booking.status = BOOKING_REJECTED
    booking.cancel_reason = str(reason).strip()[:200]
    booking.released_at = timezone.now()
    booking.save(update_fields=['status', 'cancel_reason', 'released_at', 'updated_at'])
    logger.info('room_booking_rejected id=%s by=%s', booking.pk, _actor_id(actor))
    return booking


def cancel_booking(booking, actor, reason='', *, request=None):
    """取消预约。申请人本人或具备 update 权限者可取消。"""
    if booking.status in (BOOKING_CANCELLED, BOOKING_RELEASED):
        raise FacilityError('该预约已结束', code='BAD_STATE')
    is_owner = str(getattr(booking.account, 'pk', '')) == str(getattr(actor, 'pk', ''))
    if not is_owner and not authz.has_action(actor, 'update'):
        raise FacilityError('无权取消他人的预约', code='PERMISSION_DENIED')

    booking.status = BOOKING_CANCELLED
    booking.cancel_reason = str(reason or '')[:200]
    booking.released_at = timezone.now()
    booking.save(update_fields=['status', 'cancel_reason', 'released_at', 'updated_at'])
    logger.info('room_booking_cancelled id=%s by=%s', booking.pk, _actor_id(actor))
    return booking


def check_in_booking(booking, actor, *, request=None):
    """签到。仅 approved 可签到；必须是申请人本人或管理员。"""
    if booking.status != BOOKING_APPROVED:
        raise FacilityError('只有已批准的预约可以签到', code='BAD_STATE')
    is_owner = str(getattr(booking.account, 'pk', '')) == str(getattr(actor, 'pk', ''))
    if not is_owner and not authz.has_action(actor, 'update'):
        raise FacilityError('无权为他人签到', code='PERMISSION_DENIED')

    booking.status = BOOKING_CHECKED_IN
    booking.checked_in_at = timezone.now()
    booking.save(update_fields=['status', 'checked_in_at', 'updated_at'])
    logger.info('room_booking_checked_in id=%s', booking.pk)
    return booking


def mark_no_show(booking, actor, *, request=None):
    """标记爽约（通常在预约开始后由管理员批量执行）。"""
    if booking.status not in (BOOKING_APPROVED, BOOKING_PENDING):
        raise FacilityError('只有未签到的预约可以标记爽约', code='BAD_STATE')
    if not authz.has_action(actor, 'update'):
        raise FacilityError('当前账号没有该操作权限', code='PERMISSION_DENIED')

    booking.status = BOOKING_NO_SHOW
    booking.released_at = timezone.now()
    booking.save(update_fields=['status', 'released_at', 'updated_at'])
    logger.info('room_booking_no_show id=%s by=%s', booking.pk, _actor_id(actor))
    return booking


def release_booking(booking, actor, *, request=None):
    """提前释放房间（结束占用，释放后该时段可被再次预约）。"""
    if booking.status not in (BOOKING_APPROVED, BOOKING_CHECKED_IN):
        raise FacilityError('只有进行中的预约可以释放', code='BAD_STATE')
    is_owner = str(getattr(booking.account, 'pk', '')) == str(getattr(actor, 'pk', ''))
    if not is_owner and not authz.has_action(actor, 'update'):
        raise FacilityError('无权释放他人的预约', code='PERMISSION_DENIED')

    booking.status = BOOKING_RELEASED
    booking.released_at = timezone.now()
    booking.save(update_fields=['status', 'released_at', 'updated_at'])
    logger.info('room_booking_released id=%s by=%s', booking.pk, _actor_id(actor))
    return booking


def auto_mark_no_shows(now=None, grace_minutes=15):
    """把"已过开始时间 + 宽限期仍未签到"的预约标记爽约。"""
    now = now or timezone.now()
    threshold = now - timezone.timedelta(minutes=grace_minutes)
    qs = RoomBooking.objects.filter(
        status=BOOKING_APPROVED, start_at__lt=threshold)
    count = 0
    for booking in qs:
        booking.status = BOOKING_NO_SHOW
        booking.released_at = now
        booking.save(update_fields=['status', 'released_at', 'updated_at'])
        count += 1
    if count:
        logger.info('room_booking_no_show_batch count=%s', count)
    return count


# ---------------------------------------------------------------------------
# 查询视图
# ---------------------------------------------------------------------------
def scoped_bookings(account):
    """按角色收窄的预约查询集（默认拒绝）。"""
    qs = RoomBooking.objects.select_related('room', 'account')
    roles = authz.active_roles(account)
    if not roles:
        return qs.none()
    from r21_account.models import RoleCode

    if RoleCode.SYSTEM_ADMIN in roles:
        return qs
    if RoleCode.COLLEGE_ADMIN in roles:
        scope = (getattr(account, 'scope_college', '') or '').strip()
        if not scope:
            return qs.none()
        return qs.filter(room__building__campus=scope)
    # 教师与学生只能看自己的
    return qs.filter(account=account)


def room_calendar(room, start_at, end_at):
    """共享日历：返回该房间在区间内的占用与封闭期。"""
    bookings = list(RoomBooking.objects.filter(
        room=room, status__in=OCCUPYING_STATUSES,
        start_at__lt=end_at, end_at__gt=start_at,
    ).order_by('start_at').values(
        'pk', 'start_at', 'end_at', 'status', 'purpose', 'account_id'))
    maintenances = list(MaintenanceWindow.objects.filter(
        room=room, start_at__lt=end_at, end_at__gt=start_at,
    ).order_by('start_at').values('pk', 'start_at', 'end_at', 'reason'))
    return {
        'room': {'pk': room.pk, 'code': room.code, 'name': room.name,
                 'capacity': room.capacity, 'status': room.status},
        'bookings': bookings,
        'maintenances': maintenances,
        'availability': [
            {'weekday': w.weekday, 'start': w.start_time.strftime('%H:%M'),
             'end': w.end_time.strftime('%H:%M')}
            for w in availability_windows(room)
        ],
    }


def available_rooms(start_at, end_at, *, room_type=None, min_capacity=0):
    """在指定时段内可预约的房间列表（不含权限判断）。"""
    qs = Room.objects.filter(is_active=True, status=ROOM_STATUS_OPEN)
    if room_type:
        qs = qs.filter(room_type=room_type)
    if min_capacity:
        qs = qs.filter(Q(capacity=0) | Q(capacity__gte=min_capacity))

    busy_room_ids = set(RoomBooking.objects.filter(
        status__in=OCCUPYING_STATUSES,
        start_at__lt=end_at, end_at__gt=start_at,
    ).values_list('room_id', flat=True))
    blocked_room_ids = set(MaintenanceWindow.objects.filter(
        start_at__lt=end_at, end_at__gt=start_at,
    ).values_list('room_id', flat=True))

    return [room for room in qs.select_related('building').order_by('code')
            if room.pk not in busy_room_ids and room.pk not in blocked_room_ids]
