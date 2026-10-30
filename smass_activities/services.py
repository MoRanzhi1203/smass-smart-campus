"""R14 服务层：活动发布、报名候补、签到、关闭与学分认定。

规则摘要
--------
- 报名：仅"已发布 + 未截止 + 未开始"可报名；满员进候补；取消后自动递补；
- 签到：活动进行中 + 签到码有效 + 状态为已报名；
- 关闭：未签到报名者标缺勤，并清空签到码；
- 认定：活动关闭后按签到名单生成待认定记录，管理员审批后计入累计；
- 审批禁止自批。
"""
from __future__ import annotations

import logging
import secrets
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode
from smass_organization.models import StudentRecord

from .models import (
    ACTIVITY_STATUS,
    CATEGORY_TYPES,
    CREDIT_APPROVED,
    CREDIT_PENDING,
    CREDIT_REJECTED,
    OCCUPYING_STATUSES,
    REG_ABSENT,
    REG_CANCELLED,
    REG_CHECKED_IN,
    REG_REGISTERED,
    REG_WAITLISTED,
    REGISTRATION_STATUS,
    STATUS_CANCELLED,
    STATUS_CLOSED,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    Activity,
    ActivityCredit,
    ActivityRegistration,
)

logger = logging.getLogger('smass.audit')

MANAGER_ROLES = frozenset({
    RoleCode.TEACHER, RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN,
})


class ActivityError(ValueError):
    def __init__(self, message, code='ACTIVITY_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(ActivityError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def can_manage(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & MANAGER_ROLES:
        return True
    return authz.has_action(account, 'update')


def _require_manage(account):
    if not can_manage(account):
        raise PermissionDenied('只有教师或管理员可以执行该操作')


def record_for_account(account):
    return StudentRecord.objects.filter(account=account).first()


# ---------------------------------------------------------------------------
# 活动
# ---------------------------------------------------------------------------
def create_activity(actor, title, category, start_at, end_at, *,
                    capacity=0, credit_points=0, volunteer_hours=0,
                    location='', deadline=None):
    _require_manage(actor)
    if not str(title or '').strip():
        raise ActivityError('活动名称不能为空', code='EMPTY_TITLE')
    if category not in dict(CATEGORY_TYPES):
        raise ActivityError('未知的活动类别', code='BAD_CATEGORY')
    if start_at is None or end_at is None or end_at <= start_at:
        raise ActivityError('结束时间必须晚于开始时间', code='BAD_RANGE')
    if deadline is not None and deadline > start_at:
        raise ActivityError('报名截止不能晚于活动开始', code='BAD_DEADLINE')

    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    activity = Activity.objects.create(
        title=str(title).strip()[:100],
        category=category,
        organizer=actor if getattr(actor, 'pk', None) else None,
        location=str(location or '')[:100],
        start_at=start_at,
        end_at=end_at,
        registration_deadline=deadline,
        capacity=int(capacity or 0),
        credit_points=Decimal(str(credit_points or 0)),
        volunteer_hours=Decimal(str(volunteer_hours or 0)),
        status=STATUS_DRAFT,
        checkin_code=code,
        checkin_expires_at=end_at,
        created_by=_actor_id(actor),
    )
    logger.info('activity_created id=%s title=%s by=%s',
                activity.pk, activity.title, _actor_id(actor))
    return activity


def publish_activity(activity, actor):
    _require_manage(actor)
    if activity.status != STATUS_DRAFT:
        raise ActivityError('只有草稿活动可以发布', code='BAD_STATE')
    if activity.end_at <= timezone.now():
        raise ActivityError('活动已过期，不能发布', code='PAST_ACTIVITY')
    activity.status = STATUS_PUBLISHED
    activity.save(update_fields=['status', 'updated_at'])
    logger.info('activity_published id=%s by=%s', activity.pk, _actor_id(actor))
    return activity


def cancel_activity(activity, actor):
    if not can_manage(actor) and not _is_self(actor, activity.created_by):
        raise PermissionDenied()
    if activity.status in (STATUS_CLOSED, STATUS_CANCELLED):
        raise ActivityError('活动已结束或已取消', code='BAD_STATE')
    activity.status = STATUS_CANCELLED
    activity.save(update_fields=['status', 'updated_at'])
    logger.info('activity_cancelled id=%s by=%s', activity.pk, _actor_id(actor))
    return activity


def close_activity(activity, actor):
    """关闭活动：未签到的已报名者标缺勤，清空签到码。"""
    _require_manage(actor)
    with transaction.atomic():
        locked = Activity.objects.select_for_update().get(pk=activity.pk)
        if locked.status != STATUS_PUBLISHED:
            raise ActivityError('只有已发布的活动可以关闭', code='BAD_STATE')
        locked.registrations.filter(status=REG_REGISTERED).update(status=REG_ABSENT)
        locked.status = STATUS_CLOSED
        locked.checkin_code = ''
        locked.save(update_fields=['status', 'checkin_code', 'updated_at'])

    logger.info('activity_closed id=%s by=%s', locked.pk, _actor_id(actor))
    return locked


# ---------------------------------------------------------------------------
# 报名
# ---------------------------------------------------------------------------
def _occupied(activity):
    return activity.registrations.filter(status__in=OCCUPYING_STATUSES).count()


def register(activity, record, actor):
    if record is None:
        raise ActivityError('学籍档案不存在', code='NO_RECORD')
    if not _is_self(actor, getattr(record.account, 'pk', None)):
        _require_manage(actor)
    if activity.status != STATUS_PUBLISHED:
        raise ActivityError('活动未发布或已结束', code='NOT_PUBLISHED')
    now = timezone.now()
    if activity.registration_deadline and now > activity.registration_deadline:
        raise ActivityError('报名已截止', code='DEADLINE_PASSED')
    if now >= activity.start_at:
        raise ActivityError('活动已开始，不能报名', code='ACTIVITY_STARTED')

    with transaction.atomic():
        locked = Activity.objects.select_for_update().get(pk=activity.pk)
        existing = ActivityRegistration.objects.filter(
            activity=locked, record=record).first()
        if existing is not None and existing.status != REG_CANCELLED:
            raise ActivityError('你已报名该活动', code='DUPLICATE_REGISTRATION')

        capacity = int(locked.capacity or 0)
        status = REG_REGISTERED
        if capacity and _occupied(locked) >= capacity:
            status = REG_WAITLISTED

        if existing is None:
            registration = ActivityRegistration.objects.create(
                activity=locked, record=record, status=status)
        else:
            existing.status = status
            existing.checked_in_at = None
            existing.save(update_fields=['status', 'checked_in_at'])
            registration = existing

    logger.info('activity_registered activity=%s record=%s status=%s by=%s',
                activity.pk, record.student_no, status, _actor_id(actor))
    return registration


def cancel_registration(registration, actor):
    activity = registration.activity
    if not _is_self(actor, getattr(registration.record.account, 'pk', None)) \
            and not can_manage(actor):
        raise PermissionDenied()
    if registration.status not in (REG_REGISTERED, REG_WAITLISTED):
        raise ActivityError('当前状态不能取消报名', code='BAD_STATE')

    with transaction.atomic():
        locked = ActivityRegistration.objects.select_for_update().get(
            pk=registration.pk)
        was_registered = locked.status == REG_REGISTERED
        locked.status = REG_CANCELLED
        locked.save(update_fields=['status'])

        promoted = None
        if was_registered:
            candidate = ActivityRegistration.objects.filter(
                activity_id=activity.pk, status=REG_WAITLISTED,
            ).order_by('registered_at', 'pk').first()
            if candidate is not None:
                candidate.status = REG_REGISTERED
                candidate.save(update_fields=['status'])
                promoted = candidate

    logger.info('activity_registration_cancelled id=%s by=%s promoted=%s',
                registration.pk, _actor_id(actor),
                promoted.pk if promoted else '-')
    return registration, promoted


def check_in(registration, actor, code):
    if not _is_self(actor, getattr(registration.record.account, 'pk', None)):
        _require_manage(actor)
    # 重新读取活动，避免使用调用方缓存里的过期时间窗口
    activity = Activity.objects.get(pk=registration.activity_id)
    now = timezone.now()
    if registration.status != REG_REGISTERED:
        raise ActivityError('只有已报名状态可以签到', code='BAD_STATE')
    if not (activity.start_at <= now <= activity.end_at):
        raise ActivityError('不在活动签到时间内', code='OUT_OF_WINDOW')
    if not code or str(code).strip() != activity.checkin_code:
        raise ActivityError('签到码不正确', code='BAD_CODE')
    if activity.checkin_expires_at and now > activity.checkin_expires_at:
        raise ActivityError('签到码已过期', code='CODE_EXPIRED')

    registration.status = REG_CHECKED_IN
    registration.checked_in_at = now
    registration.save(update_fields=['status', 'checked_in_at'])
    logger.info('activity_checked_in activity=%s record=%s',
                activity.pk, registration.record.student_no)
    return registration


# ---------------------------------------------------------------------------
# 学分认定
# ---------------------------------------------------------------------------
def generate_credits(activity, actor):
    """活动关闭后，为已签到学生生成待认定记录（幂等）。"""
    _require_manage(actor)
    # 重新读取，避免调用方缓存里的旧状态
    activity = Activity.objects.get(pk=activity.pk)
    if activity.status != STATUS_CLOSED:
        raise ActivityError('只有已结束的活动可以生成认定', code='BAD_STATE')

    created = 0
    for registration in activity.registrations.filter(status=REG_CHECKED_IN):
        _, is_new = ActivityCredit.objects.get_or_create(
            activity=activity, record=registration.record,
            defaults={
                'category': activity.category,
                'points': activity.credit_points,
                'hours': activity.volunteer_hours,
                'status': CREDIT_PENDING,
            },
        )
        created += 1 if is_new else 0
    logger.info('activity_credits_generated activity=%s created=%s by=%s',
                activity.pk, created, _actor_id(actor))
    return created


def approve_credit(credit, actor):
    _require_manage(actor)
    if credit.status != CREDIT_PENDING:
        raise ActivityError('只有待认定的记录可以批准', code='BAD_STATE')
    if _is_self(actor, credit.activity.created_by) or \
            _is_self(actor, getattr(credit.activity.organizer, 'pk', None)):
        # 组织者/创建人不能认定自己组织的活动（与 S12 职责分离一致）
        raise ActivityError('不能认定自己组织的活动学分（职责分离）',
                            code='SELF_APPROVAL_DENIED')
    credit.status = CREDIT_APPROVED
    credit.reviewed_by = _actor_id(actor)
    credit.reviewed_at = timezone.now()
    credit.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    logger.info('activity_credit_approved id=%s by=%s',
                credit.pk, _actor_id(actor))
    return credit


def reject_credit(credit, actor, reason):
    _require_manage(actor)
    if credit.status != CREDIT_PENDING:
        raise ActivityError('只有待认定的记录可以驳回', code='BAD_STATE')
    if not str(reason or '').strip():
        raise ActivityError('驳回必须填写原因', code='EMPTY_REASON')
    credit.status = CREDIT_REJECTED
    credit.reviewed_by = _actor_id(actor)
    credit.reviewed_at = timezone.now()
    credit.reject_reason = str(reason).strip()[:255]
    credit.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                               'reject_reason'])
    logger.info('activity_credit_rejected id=%s by=%s',
                credit.pk, _actor_id(actor))
    return credit


# ---------------------------------------------------------------------------
# 查询与统计
# ---------------------------------------------------------------------------
def scoped_activities(account, status=None):
    qs = Activity.objects.select_related('organizer')
    if status:
        qs = qs.filter(status=status)
    if can_manage(account):
        return qs.order_by('-start_at')
    return qs.filter(status__in=[STATUS_PUBLISHED, STATUS_CLOSED]).order_by('-start_at')


def scoped_registrations(account, activity=None):
    qs = ActivityRegistration.objects.select_related('activity', 'record')
    if activity is not None:
        qs = qs.filter(activity=activity)
    if can_manage(account):
        return qs.order_by('-registered_at')
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record).order_by('-registered_at')


def scoped_credits(account):
    qs = ActivityCredit.objects.select_related('activity', 'record')
    if can_manage(account):
        return qs.order_by('-created_at')
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record).order_by('-created_at')


def credit_summary(record):
    """已认定学分与志愿时长累计。"""
    rows = ActivityCredit.objects.filter(record=record, status=CREDIT_APPROVED)
    points = sum((row.points for row in rows), Decimal('0'))
    hours = sum((row.hours for row in rows), Decimal('0'))
    return {'points': points, 'hours': hours, 'count': rows.count()}


def activity_stats(activity):
    rows = activity.registrations.all()
    stats = {code: 0 for code, _label in REGISTRATION_STATUS}
    for row in rows:
        stats[row.status] = stats.get(row.status, 0) + 1
    stats['total'] = rows.count()
    return stats
