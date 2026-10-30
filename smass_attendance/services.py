"""R13 服务层：签到、关闭会话、请假销假与补签。

所有写操作只经本模块。关键约束：

- 签到码由服务端生成并带过期时间；重复签到幂等返回既有记录；
- 关闭会话时自动为未签到学生补"缺勤"，请假覆盖当日的学生标"请假"；
- 请假批准时检查与其它已批准请假是否重叠（同一学生同一时间只能有一条有效请假）；
- 补签只对已关闭会话的缺勤/迟到记录开放，批准后覆盖为出勤；
- 审批人不得是提交人（与 S12 一致）。
"""
from __future__ import annotations

import logging
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode
from smass_organization.models import StudentRecord

from .models import (
    ATTENDED_STATUSES,
    LEAVE_APPROVED,
    LEAVE_CANCELLED,
    LEAVE_CLOSED,
    LEAVE_REJECTED,
    LEAVE_SUBMITTED,
    LEAVE_TYPES,
    MAKEUP_APPROVED,
    MAKEUP_REJECTED,
    MAKEUP_SUBMITTED,
    RECORD_ABSENT,
    RECORD_LATE,
    RECORD_LEAVE,
    RECORD_PRESENT,
    RECORD_STATUS,
    SESSION_CLOSED,
    SESSION_OPEN,
    SOURCE_MAKEUP,
    SOURCE_SELF,
    SOURCE_TEACHER,
    AttendanceRecord,
    AttendanceSession,
    LeaveRequest,
    MakeupRequest,
)

logger = logging.getLogger('smass.audit')

CODE_DIGITS = '0123456789'


class AttendanceError(ValueError):
    def __init__(self, message, code='ATTENDANCE_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(AttendanceError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def roles_of(account):
    return authz.active_roles(account)


#: 可管理考勤的角色（教师/辅导员、学院管理员、系统管理员）
MANAGER_ROLES = frozenset({
    RoleCode.TEACHER, RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN,
})


def can_manage(account):
    """教师或管理员。

    既有 RBAC 矩阵里教师只有 ``view_data``，而考勤管理是本模块的业务权限，
    因此在角色白名单上判定，而不是复用 ``update``（避免为了一个模块放宽全局矩阵）。
    无角色 / 非本模块角色一律拒绝。
    """
    roles = roles_of(account)
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


def _record_or_error(account):
    record = record_for_account(account)
    if record is None:
        raise AttendanceError('当前账号没有学籍档案', code='NO_RECORD')
    return record


# ---------------------------------------------------------------------------
# 考勤会话
# ---------------------------------------------------------------------------
def create_session(unit, session_date, period, actor, *, topic='',
                   expires_minutes=10, late_after_minutes=10):
    """创建考勤会话并生成签到码。"""
    _require_manage(actor)
    if unit is None or unit.unit_type != 'class':
        raise AttendanceError('考勤对象必须是行政班', code='BAD_UNIT')
    if AttendanceSession.objects.filter(
            unit=unit, session_date=session_date, period=period).exists():
        raise AttendanceError('同一班级该节次已有考勤会话', code='DUPLICATE_SESSION')

    code = ''.join(secrets.choice(CODE_DIGITS) for _ in range(6))
    now = timezone.now()
    session = AttendanceSession.objects.create(
        unit=unit,
        session_date=session_date,
        period=period,
        topic=str(topic or '')[:100],
        status=SESSION_OPEN,
        code=code,
        code_expires_at=now + timezone.timedelta(minutes=max(1, expires_minutes)),
        late_after_minutes=max(0, int(late_after_minutes)),
        created_by=_actor_id(actor),
    )
    logger.info('attendance_session_created id=%s unit=%s by=%s',
                session.pk, unit.code, _actor_id(actor))
    return session


def close_session(session, actor):
    """关闭会话：未签到学生补缺勤，请假覆盖当日者标请假。"""
    _require_manage(actor)
    with transaction.atomic():
        locked = AttendanceSession.objects.select_for_update().get(pk=session.pk)
        if locked.status != SESSION_OPEN:
            raise AttendanceError('该考勤会话已关闭', code='SESSION_CLOSED')

        students = list(StudentRecord.objects.filter(
            unit=locked.unit, status='enrolled'))
        marked = set(AttendanceRecord.objects.filter(
            session=locked).values_list('record_id', flat=True))
        leave_ids = set(LeaveRequest.objects.filter(
            status=LEAVE_APPROVED,
            start_date__lte=locked.session_date,
            end_date__gte=locked.session_date,
        ).values_list('record_id', flat=True))

        for student in students:
            if student.pk in marked:
                continue
            status = RECORD_LEAVE if student.pk in leave_ids else RECORD_ABSENT
            AttendanceRecord.objects.create(
                session=locked, record=student, status=status,
                source=SOURCE_TEACHER,
                note='关闭会话自动补记')

        locked.status = SESSION_CLOSED
        locked.closed_at = timezone.now()
        locked.code = ''
        locked.save(update_fields=['status', 'closed_at', 'code'])

    logger.info('attendance_session_closed id=%s by=%s students=%s',
                locked.pk, _actor_id(actor), len(students))
    return locked


def teacher_mark(session, student, status, actor, *, note=''):
    """教师手动标记某个学生的考勤状态（upsert）。"""
    _require_manage(actor)
    if student is None:
        raise AttendanceError('学生不存在', code='NO_RECORD')
    if status not in dict(RECORD_STATUS):
        raise AttendanceError('未知的考勤状态', code='BAD_STATUS')
    if student.unit_id != session.unit_id:
        raise AttendanceError('学生不属于该班级', code='NOT_IN_CLASS')

    record, _created = AttendanceRecord.objects.update_or_create(
        session=session, record=student,
        defaults={'status': status, 'source': SOURCE_TEACHER,
                  'checked_at': timezone.now(), 'note': str(note or '')[:200]},
    )
    logger.info('attendance_teacher_mark session=%s student=%s status=%s by=%s',
                session.pk, student.student_no, status, _actor_id(actor))
    return record


def sign_in(session, account, code, *, ip=''):
    """学生签到；返回 (record, created)。"""
    record = _record_or_error(account)
    if record.unit_id != session.unit_id:
        raise AttendanceError('你不属于该考勤班级', code='NOT_IN_CLASS')
    if session.status != SESSION_OPEN:
        raise AttendanceError('签到已结束', code='SESSION_CLOSED')
    if not code or str(code).strip() != session.code:
        raise AttendanceError('签到码不正确', code='BAD_CODE')
    now = timezone.now()
    if session.code_expires_at and now > session.code_expires_at:
        raise AttendanceError('签到码已过期，请联系教师补签', code='CODE_EXPIRED')

    late = (now - session.created_at) > timezone.timedelta(
        minutes=int(session.late_after_minutes or 0))
    created = None
    with transaction.atomic():
        try:
            with transaction.atomic():  # savepoint：唯一约束冲突不污染外层事务
                created = AttendanceRecord.objects.create(
                    session=session, record=record,
                    status=RECORD_LATE if late else RECORD_PRESENT,
                    source=SOURCE_SELF, checked_at=now, ip=str(ip or '')[:64],
                )
        except IntegrityError:
            created = None
    if created is None:
        # 并发/重复提交：返回既有记录，保持幂等
        return AttendanceRecord.objects.get(session=session, record=record), False

    logger.info('attendance_signed session=%s student=%s status=%s ip=%s',
                session.pk, record.student_no, created.status, ip or '-')
    return created, True


# ---------------------------------------------------------------------------
# 请假
# ---------------------------------------------------------------------------
def _overlapping_leave(record, start_date, end_date, *, exclude_id=None):
    qs = LeaveRequest.objects.filter(
        record=record, status=LEAVE_APPROVED,
        start_date__lte=end_date, end_date__gte=start_date,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.first()


def submit_leave(record, leave_type, start_date, end_date, reason, actor):
    if record is None:
        raise AttendanceError('学籍档案不存在', code='NO_RECORD')
    if not _is_self(actor, getattr(record.account, 'pk', None)):
        _require_manage(actor)
    if leave_type not in dict(LEAVE_TYPES):
        raise AttendanceError('未知的请假类型', code='BAD_TYPE')
    if start_date is None or end_date is None:
        raise AttendanceError('请填写请假起止日期', code='MISSING_DATE')
    if end_date < start_date:
        raise AttendanceError('结束日期不能早于开始日期', code='BAD_RANGE')
    if not str(reason or '').strip():
        raise AttendanceError('请假必须填写事由', code='EMPTY_REASON')

    with transaction.atomic():
        locked = StudentRecord.objects.select_for_update().get(pk=record.pk)
        if locked.status in ('withdrawn', 'graduated'):
            raise AttendanceError('已离校学生不能请假', code='TERMINAL_STATUS')
        if LeaveRequest.objects.filter(
                record=locked,
                status__in=[LEAVE_SUBMITTED, LEAVE_APPROVED],
                start_date__lte=end_date, end_date__gte=start_date,
        ).exists():
            raise AttendanceError('该时间段已有进行中的请假申请', code='DUPLICATE_REQUEST')

        leave = LeaveRequest.objects.create(
            record=locked, leave_type=leave_type,
            start_date=start_date, end_date=end_date,
            reason=str(reason).strip()[:500],
            submitted_by=_actor_id(actor),
            status=LEAVE_SUBMITTED,
        )
    logger.info('leave_submitted id=%s record=%s %s~%s by=%s',
                leave.pk, record.student_no, start_date, end_date, _actor_id(actor))
    return leave


def approve_leave(leave, actor):
    _require_manage(actor)
    if leave.status != LEAVE_SUBMITTED:
        raise AttendanceError('只有待审批的请假可以批准', code='BAD_STATE')
    if _is_self(actor, leave.submitted_by):
        raise AttendanceError('不能审批自己提交的请假（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    conflict = _overlapping_leave(
        leave.record, leave.start_date, leave.end_date, exclude_id=leave.pk)
    if conflict is not None:
        raise AttendanceError(
            '与已批准的请假（{}~{}）冲突'.format(conflict.start_date, conflict.end_date),
            code='LEAVE_OVERLAP')

    leave.status = LEAVE_APPROVED
    leave.reviewed_by = _actor_id(actor)
    leave.reviewed_at = timezone.now()
    leave.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
    logger.info('leave_approved id=%s by=%s', leave.pk, _actor_id(actor))
    return leave


def reject_leave(leave, actor, reason):
    _require_manage(actor)
    if leave.status != LEAVE_SUBMITTED:
        raise AttendanceError('只有待审批的请假可以驳回', code='BAD_STATE')
    if _is_self(actor, leave.submitted_by):
        raise AttendanceError('不能驳回自己提交的请假（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise AttendanceError('驳回必须填写原因', code='EMPTY_REASON')

    leave.status = LEAVE_REJECTED
    leave.reviewed_by = _actor_id(actor)
    leave.reviewed_at = timezone.now()
    leave.reject_reason = str(reason).strip()[:255]
    leave.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'reject_reason', 'updated_at'])
    logger.info('leave_rejected id=%s by=%s', leave.pk, _actor_id(actor))
    return leave


def cancel_leave(leave, actor):
    if leave.status != LEAVE_SUBMITTED:
        raise AttendanceError('只有待审批的请假可以撤销', code='BAD_STATE')
    if not _is_self(actor, leave.submitted_by) and not can_manage(actor):
        raise PermissionDenied()
    leave.status = LEAVE_CANCELLED
    leave.save(update_fields=['status', 'updated_at'])
    logger.info('leave_cancelled id=%s by=%s', leave.pk, _actor_id(actor))
    return leave


def close_leave(leave, actor):
    """销假：批准且已过结束日期后，由本人或管理员销假。"""
    if leave.status != LEAVE_APPROVED:
        raise AttendanceError('只有已批准的请假可以销假', code='BAD_STATE')
    if not _is_self(actor, leave.submitted_by) and not can_manage(actor):
        raise PermissionDenied()
    if leave.end_date > timezone.localdate():
        raise AttendanceError('请假尚未结束，不能提前销假', code='NOT_FINISHED')

    leave.status = LEAVE_CLOSED
    leave.closed_at = timezone.now()
    leave.save(update_fields=['status', 'closed_at', 'updated_at'])
    logger.info('leave_closed id=%s by=%s', leave.pk, _actor_id(actor))
    return leave


# ---------------------------------------------------------------------------
# 补签
# ---------------------------------------------------------------------------
def submit_makeup(record, session, reason, actor):
    if record is None or session is None:
        raise AttendanceError('缺少学籍档案或考勤会话', code='MISSING_ARGUMENT')
    if not _is_self(actor, getattr(record.account, 'pk', None)):
        _require_manage(actor)
    if session.status != SESSION_CLOSED:
        raise AttendanceError('只有已关闭的考勤会话可以补签', code='SESSION_OPEN')
    if not str(reason or '').strip():
        raise AttendanceError('补签必须填写理由', code='EMPTY_REASON')

    attendance = AttendanceRecord.objects.filter(
        session=session, record=record).first()
    if attendance is None:
        raise AttendanceError('该会话没有你的考勤记录', code='NO_RECORD_ROW')
    if attendance.status == RECORD_PRESENT:
        raise AttendanceError('你已出勤，无需补签', code='ALREADY_PRESENT')

    with transaction.atomic():
        locked = StudentRecord.objects.select_for_update().get(pk=record.pk)
        if MakeupRequest.objects.filter(
                record=locked, session=session,
                status__in=[MAKEUP_SUBMITTED, MAKEUP_APPROVED]).exists():
            raise AttendanceError('该会话已有进行中的补签申请', code='DUPLICATE_REQUEST')
        makeup = MakeupRequest.objects.create(
            record=locked, session=session,
            reason=str(reason).strip()[:500],
            submitted_by=_actor_id(actor),
            status=MAKEUP_SUBMITTED,
        )
    logger.info('makeup_submitted id=%s session=%s record=%s by=%s',
                makeup.pk, session.pk, record.student_no, _actor_id(actor))
    return makeup


def approve_makeup(makeup, actor):
    """批准补签：把缺勤/迟到记录覆盖为出勤（source=makeup）。"""
    _require_manage(actor)
    if makeup.status != MAKEUP_SUBMITTED:
        raise AttendanceError('只有待审批的补签可以批准', code='BAD_STATE')
    if _is_self(actor, makeup.submitted_by):
        raise AttendanceError('不能审批自己提交的补签（职责分离）',
                              code='SELF_APPROVAL_DENIED')

    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().filter(
            session=makeup.session, record=makeup.record).first()
        if record is None:
            raise AttendanceError('考勤记录不存在', code='NO_RECORD_ROW')
        record.status = RECORD_PRESENT
        record.source = SOURCE_MAKEUP
        record.note = '补签批准（申请 {}）'.format(makeup.pk)[:200]
        record.save(update_fields=['status', 'source', 'note'])

        makeup.status = MAKEUP_APPROVED
        makeup.reviewed_by = _actor_id(actor)
        makeup.reviewed_at = timezone.now()
        makeup.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'updated_at'])

    logger.info('makeup_approved id=%s session=%s record=%s by=%s',
                makeup.pk, makeup.session_id, makeup.record.student_no,
                _actor_id(actor))
    return makeup


def reject_makeup(makeup, actor, reason):
    _require_manage(actor)
    if makeup.status != MAKEUP_SUBMITTED:
        raise AttendanceError('只有待审批的补签可以驳回', code='BAD_STATE')
    if _is_self(actor, makeup.submitted_by):
        raise AttendanceError('不能驳回自己提交的补签（职责分离）',
                              code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise AttendanceError('驳回必须填写原因', code='EMPTY_REASON')

    makeup.status = MAKEUP_REJECTED
    makeup.reviewed_by = _actor_id(actor)
    makeup.reviewed_at = timezone.now()
    makeup.reject_reason = str(reason).strip()[:255]
    makeup.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'reject_reason', 'updated_at'])
    logger.info('makeup_rejected id=%s by=%s', makeup.pk, _actor_id(actor))
    return makeup


# ---------------------------------------------------------------------------
# 查询与统计
# ---------------------------------------------------------------------------
def scoped_sessions(account):
    qs = AttendanceSession.objects.select_related('unit')
    if can_manage(account):
        return qs
    record = record_for_account(account)
    if record is None or record.unit is None:
        return qs.none()
    return qs.filter(unit=record.unit)


def scoped_leaves(account):
    qs = LeaveRequest.objects.select_related('record')
    if can_manage(account):
        return qs
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def scoped_makeups(account):
    qs = MakeupRequest.objects.select_related('record', 'session')
    if can_manage(account):
        return qs
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def session_stats(session):
    """单个会话的出勤统计。"""
    rows = list(AttendanceRecord.objects.filter(session=session))
    counts = {code: 0 for code, _label in RECORD_STATUS}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    total = len(rows)
    attended = counts.get(RECORD_PRESENT, 0) + counts.get(RECORD_LATE, 0)
    return {
        'total': total,
        'present': counts.get(RECORD_PRESENT, 0),
        'late': counts.get(RECORD_LATE, 0),
        'absent': counts.get(RECORD_ABSENT, 0),
        'leave': counts.get(RECORD_LEAVE, 0),
        'rate': round(attended * 100.0 / total, 1) if total else 0.0,
    }


def unit_stats(unit, date_from=None, date_to=None):
    """按学生汇总班级出勤率（用于统计页）。"""
    sessions = AttendanceSession.objects.filter(unit=unit)
    if date_from:
        sessions = sessions.filter(session_date__gte=date_from)
    if date_to:
        sessions = sessions.filter(session_date__lte=date_to)
    session_ids = list(sessions.values_list('pk', flat=True))
    rows = AttendanceRecord.objects.filter(
        session_id__in=session_ids).select_related('record')
    per_student = {}
    for row in rows:
        bucket = per_student.setdefault(row.record_id, {
            'record': row.record, 'present': 0, 'late': 0, 'absent': 0, 'leave': 0})
        bucket[row.status] = bucket.get(row.status, 0) + 1
    result = []
    for bucket in per_student.values():
        total = bucket['present'] + bucket['late'] + bucket['absent'] + bucket['leave']
        attended = bucket['present'] + bucket['late']
        bucket['total'] = total
        bucket['rate'] = round(attended * 100.0 / total, 1) if total else 0.0
        result.append(bucket)
    return sorted(result, key=lambda item: item['record'].student_no)


def attendance_statuses():
    return list(ATTENDED_STATUSES)
