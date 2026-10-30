"""学生端数据聚合。

原则
----
- 只读；写操作走各业务模块自己的服务函数（保持唯一业务规则来源）；
- 账号没有学籍档案时返回 ``None`` / 空集，由页面显示真实空状态，绝不编造数字；
- 所有查询都带 ``select_related``，避免列表页 N+1。
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count
from django.utils import timezone


# ---------------------------------------------------------------------------
# 身份与学籍
# ---------------------------------------------------------------------------
def student_record(account):
    from smass_organization.models import StudentRecord

    if account is None or not getattr(account, 'is_authenticated', False):
        return None
    return (StudentRecord.objects.filter(account=account)
            .select_related('unit', 'unit__parent', 'unit__parent__parent')
            .first())


def record_chain(record):
    """返回 (学院, 专业, 班级) 名称，缺失项为空串。"""
    if record is None or record.unit is None:
        return '', '', ''
    chain = list(record.unit.ancestors())
    names = {}
    for unit in chain:
        names.setdefault(unit.unit_type, unit.name)
    return (names.get('college', ''), names.get('major', ''),
            names.get('class', record.unit.name if record.unit.unit_type == 'class' else ''))


def profile_of(account):
    from r21_account.models import StudentProfile

    if account is None:
        return None
    return StudentProfile.objects.filter(account=account).first()


def dormitory_of(record):
    """寝室信息：优先统一学籍扩展字段，其次历史 app01 档案（只读桥接）。"""
    if record is None:
        return None
    extra = record.extra or {}
    dorm = extra.get('dormitory')
    if isinstance(dorm, dict) and (dorm.get('building') or dorm.get('room')):
        return {
            'building': dorm.get('building', ''),
            'room': dorm.get('room', ''),
            'bed': dorm.get('bed', ''),
            'roommates': dorm.get('roommates') or [],
            'source': '学籍档案',
        }
    try:
        from app01.models import Student

        legacy = Student.objects.filter(id=record.student_no).first()
    except Exception:  # noqa: BLE001 - 历史表缺失时按无数据处理
        legacy = None
    if legacy is not None and (legacy.building or legacy.dormitory):
        return {
            'building': legacy.building or '',
            'room': legacy.dormitory or '',
            'bed': '',
            'roommates': [],
            'source': '历史学籍档案',
        }
    return None


# ---------------------------------------------------------------------------
# 学期与课表
# ---------------------------------------------------------------------------
def current_term():
    from smass_academic.models import AcademicTerm

    term = (AcademicTerm.objects.filter(is_active=True)
            .select_related('year').order_by('-year__start_date').first())
    if term is not None:
        return term
    return (AcademicTerm.objects.select_related('year')
            .order_by('-year__start_date', '-semester').first())


def published_run():
    from smass_scheduling.models import RUN_PUBLISHED, ScheduleRun

    term = current_term()
    runs = ScheduleRun.objects.filter(status=RUN_PUBLISHED).select_related('term')
    if term is not None:
        run = runs.filter(term=term).order_by('-published_at', '-id').first()
        if run is not None:
            return run
    return runs.order_by('-published_at', '-id').first()


def student_entries(account, run=None):
    from smass_academic.models import Enrollment
    from smass_scheduling.models import ScheduleEntry

    if account is None or not getattr(account, 'is_authenticated', False):
        return []
    run = run or published_run()
    if run is None:
        return []
    section_ids = list(
        Enrollment.objects.filter(account=account).exclude(status='dropped')
        .values_list('section_id', flat=True))
    if not section_ids:
        return []
    return list(
        ScheduleEntry.objects.filter(run=run, requirement__section_id__in=section_ids)
        .select_related('requirement', 'requirement__section',
                        'requirement__section__course', 'requirement__section__term',
                        'room', 'room__building', 'teacher', 'cohort')
        .order_by('weekday', 'period'))


def week_grid(entries, periods=12, days=7):
    """把课表条目转成 ``grid[(weekday, period)] = entry``。"""
    grid = {}
    for entry in entries:
        grid[(entry.weekday, entry.period)] = entry
    return grid


def grid_rows(entries, periods):
    """模板可直接遍历的行结构：``[(节次, [周一…周日])]``。"""
    grid = week_grid(entries, periods=periods)
    return [(period, [grid.get((day, period)) for day in range(7)])
            for period in range(1, periods + 1)]


def week_span(entries):
    if not entries:
        return 12
    return max(12, max(entry.period for entry in entries))


def today_index():
    """周一=0 … 周日=6。"""
    return timezone.localdate().weekday()


def todays_entries(entries):
    today = today_index()
    return sorted([entry for entry in entries if entry.weekday == today],
                  key=lambda entry: entry.period)


# ---------------------------------------------------------------------------
# 课程
# ---------------------------------------------------------------------------
def courses_of(account):
    from smass_academic.models import Enrollment

    if account is None:
        return []
    return list(
        Enrollment.objects.filter(account=account).exclude(status='dropped')
        .select_related('section', 'section__course', 'section__term',
                        'section__term__year')
        .order_by('section__term__year__start_date', 'section__course__title'))


def section_teachers(section_ids):
    """教学班 → 任课教师列表。"""
    from smass_academic.models import TeachingAssignment

    mapping = {}
    for assignment in (TeachingAssignment.objects
                       .filter(section_id__in=list(section_ids),
                               revoked_at__isnull=True)
                       .select_related('account')):
        mapping.setdefault(assignment.section_id, []).append(
            assignment.account.display_name or assignment.account.login_name)
    return mapping


# ---------------------------------------------------------------------------
# 考勤与请假
# ---------------------------------------------------------------------------
def attendance_overview(account):
    from smass_attendance.models import (
        LEAVE_STATUS, LEAVE_SUBMITTED, AttendanceRecord, LeaveRequest,
    )

    record = student_record(account)
    if record is None:
        return {'record': None, 'counts': {}, 'recent': [], 'leaves': [],
                'pending_leaves': 0, 'rate': None}

    records = list(AttendanceRecord.objects.filter(record=record)
                   .select_related('session', 'session__unit')
                   .order_by('-session__session_date', '-session__id')[:80])
    counts = {}
    for item in records:
        counts[item.status] = counts.get(item.status, 0) + 1
    total = len(records)
    present = counts.get('present', 0) + counts.get('late', 0)
    rate = round(present * 100 / total) if total else None

    leaves = list(LeaveRequest.objects.filter(record=record)
                  .order_by('-created_at')[:30])
    pending = LeaveRequest.objects.filter(
        record=record, status=LEAVE_SUBMITTED).count()

    return {
        'record': record,
        'counts': counts,
        'recent': records[:12],
        'leaves': leaves,
        'pending_leaves': pending,
        'rate': rate,
        'leave_status': LEAVE_STATUS,
    }


# ---------------------------------------------------------------------------
# 费用
# ---------------------------------------------------------------------------
def bills_of(account):
    from smass_finance.models import Bill

    record = student_record(account)
    if record is None:
        return []
    return list(Bill.objects.filter(record=record).order_by('-created_at'))


def bill_summary(bills):
    from decimal import Decimal

    total = sum((bill.total for bill in bills), Decimal('0'))
    paid = sum((bill.paid for bill in bills), Decimal('0'))
    unpaid = sum((bill.total - bill.paid for bill in bills
                  if bill.status not in ('paid', 'cancelled')), Decimal('0'))
    return {'total': total, 'paid': paid, 'unpaid': unpaid}


# ---------------------------------------------------------------------------
# 场地预约
# ---------------------------------------------------------------------------
def bookings_of(account, limit=30):
    from smass_facilities.models import RoomBooking

    return list(RoomBooking.objects.filter(account=account)
                .select_related('room', 'room__building')
                .order_by('-start_at')[:limit])


# ---------------------------------------------------------------------------
# 活动 / 志愿
# ---------------------------------------------------------------------------
def activities_overview(account):
    from smass_activities.models import (
        ACTIVITY_STATUS, Activity, ActivityRegistration, STATUS_PUBLISHED,
    )

    record = student_record(account)
    now = timezone.now()
    published = list(
        Activity.objects.filter(status=STATUS_PUBLISHED)
        .select_related('organizer')
        .annotate(registration_count=Count('registrations'))
        .order_by('start_at'))
    regs = {}
    if record is not None:
        for reg in ActivityRegistration.objects.filter(
                record=record).select_related('activity'):
            regs[reg.activity_id] = reg
    upcoming = [item for item in published if item.end_at and item.end_at >= now]
    return {
        'record': record,
        'upcoming': upcoming,
        'all': published,
        'registrations': regs,
        'status_choices': ACTIVITY_STATUS,
    }


def volunteer_summary(account):
    from smass_activities.models import ActivityCredit

    record = student_record(account)
    if record is None:
        return {'credits': [], 'hours': 0, 'points': 0}
    credits = list(ActivityCredit.objects.filter(record=record)
                   .select_related('activity').order_by('-created_at'))
    approved = [item for item in credits if item.status == 'approved']
    return {
        'credits': credits,
        'hours': sum((item.hours for item in approved), 0),
        'points': sum((item.points for item in approved), 0),
        'participated': len(credits),
    }


# ---------------------------------------------------------------------------
# 社团 / 组织
# ---------------------------------------------------------------------------
def clubs_overview(account):
    from smass_clubs.models import Club, ClubMembership, ClubPost

    record = student_record(account)
    memberships = {}
    posts = {}
    if record is not None:
        for membership in ClubMembership.objects.filter(
                record=record).select_related('club'):
            memberships[membership.club_id] = membership
        for post in ClubPost.objects.filter(record=record).select_related('club'):
            posts[post.club_id] = post
    return {
        'clubs': list(Club.objects.select_related('advisor', 'parent')
                      .order_by('category', 'name')),
        'memberships': memberships,
        'posts': posts,
        'record': record,
    }


def organizations_overview(account):
    from smass_organization.models import OrganizationMembership, OrganizationUnit

    memberships = []
    departments = []
    if account is not None and getattr(account, 'is_authenticated', False):
        memberships = list(
            OrganizationMembership.objects.filter(
                account=account, ended_at__isnull=True)
            .select_related('unit'))
    departments = list(
        OrganizationUnit.objects.filter(
            unit_type='department', status='active')
        .order_by('sort_order', 'code'))
    return {
        'memberships': memberships,
        'departments': departments,
        'record': student_record(account),
    }


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
def announcements_for(audience='student', limit=20):
    from smass_forum.models import Announcement

    items = []
    for note in (Announcement.objects.filter(status='published')
                 .order_by('-published_at', '-created_at')[:limit * 2]):
        if note.audience in ('all', audience):
            items.append(note)
        if len(items) >= limit:
            break
    return items


def upcoming_deadlines(account, limit=5):
    """学生首页"待办"：未缴账单、待审批请假、可报名活动、即将开始预约。"""
    items = []
    for bill in bills_of(account):
        if bill.status not in ('paid', 'cancelled') and bill.total > bill.paid:
            items.append({
                'kind': '费用',
                'title': '待缴费用 {}'.format(bill.bill_no),
                'detail': '应缴 {:.2f} / 已缴 {:.2f}'.format(bill.total, bill.paid),
                'url': '/student/fees/',
            })

    overview = attendance_overview(account)
    for leave in overview['leaves']:
        if leave.status == 'submitted':
            items.append({
                'kind': '请假',
                'title': '请假申请审批中',
                'detail': '{} 至 {}'.format(leave.start_date, leave.end_date),
                'url': '/student/attendance/',
            })

    activities = activities_overview(account)
    now = timezone.now()
    for activity in activities['upcoming']:
        reg = activities['registrations'].get(activity.id)
        if reg is None and activity.registration_deadline and activity.registration_deadline >= now:
            items.append({
                'kind': '活动',
                'title': '可报名：{}'.format(activity.title),
                'detail': '报名截止 {}'.format(
                    timezone.localtime(activity.registration_deadline).strftime('%m-%d %H:%M')),
                'url': '/student/activities/',
            })
        if len(items) >= limit:
            break
    return items[:limit]


def term_week_number(term):
    """当前教学周；不在学期区间内返回 ``None``（不虚报周次）。"""
    if term is None or term.start_date is None or term.end_date is None:
        return None
    today = timezone.localdate()
    if today < term.start_date or today > term.end_date:
        return None
    return (today - term.start_date).days // 7 + 1
