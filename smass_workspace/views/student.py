"""学生工作台视图。

所有写操作都调用各业务模块的服务函数（而不是直接写库），
因此权限判定、状态机、冲突检测与学生端页面**共用同一套业务规则**。
"""
from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST

from .. import permissions as perms
from ..services import student as svc

student_only = perms.require_kind(perms.KIND_STUDENT)


def _ctx(request, **extra):
    base = {'workspace_kind': perms.KIND_STUDENT, 'record': svc.student_record(request.user)}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# 学习工作台
# ---------------------------------------------------------------------------
@require_GET
@student_only
def home(request):
    account = request.user
    record = svc.student_record(account)
    entries = svc.student_entries(account)
    courses = svc.courses_of(account)
    attendance = svc.attendance_overview(account)
    bills = svc.bills_of(account)
    activities = svc.activities_overview(account)
    volunteer = svc.volunteer_summary(account)
    term = svc.current_term()
    run = svc.published_run()
    today = svc.todays_entries(entries)

    return render(request, 'workspace/student/home.html', _ctx(
        request,
        record=record,
        chain=svc.record_chain(record),
        profile=svc.profile_of(account),
        term=term,
        week=svc.term_week_number(term),
        run=run,
        today=today,
        today_index=svc.today_index(),
        rows=svc.grid_rows(entries, svc.week_span(entries)),
        courses=courses,
        course_count=len(courses),
        attendance=attendance,
        bills=bills,
        bill_summary=svc.bill_summary(bills),
        activities=activities,
        volunteer=volunteer,
        upcoming=activities['upcoming'][:4],
        deadlines=svc.upcoming_deadlines(account),
        notices=svc.announcements_for('student', limit=6),
        week_periods=svc.week_span(entries),
        grid=svc.week_grid(entries, periods=svc.week_span(entries)),
    ))


@require_GET
@student_only
def timetable(request):
    account = request.user
    entries = svc.student_entries(account)
    term = svc.current_term()
    run = svc.published_run()
    periods = svc.week_span(entries)
    return render(request, 'workspace/student/timetable.html', _ctx(
        request,
        term=term,
        week=svc.term_week_number(term),
        run=run,
        entries=entries,
        grid=svc.week_grid(entries, periods=periods),
        rows=svc.grid_rows(entries, periods),
        periods=range(1, periods + 1),
        today=svc.today_index(),
    ))


@require_GET
@student_only
def courses(request):
    account = request.user
    enrollments = svc.courses_of(account)
    teachers = svc.section_teachers(
        [item.section_id for item in enrollments])
    attendance = svc.attendance_overview(account)
    rows = [{'item': item, 'teachers': teachers.get(item.section_id, [])}
            for item in enrollments]
    return render(request, 'workspace/student/courses.html', _ctx(
        request,
        enrollments=enrollments,
        rows=rows,
        term=svc.current_term(),
        attendance=attendance,
    ))


@require_GET
@student_only
def record(request):
    account = request.user
    record_obj = svc.student_record(account)
    changes = []
    if record_obj is not None:
        from smass_organization.models import StudentRecordChange

        changes = list(StudentRecordChange.objects.filter(record=record_obj)
                       .order_by('-changed_at')[:20])
    return render(request, 'workspace/student/record.html', _ctx(
        request,
        record=record_obj,
        chain=svc.record_chain(record_obj),
        profile=svc.profile_of(account),
        changes=changes,
        dormitory=svc.dormitory_of(record_obj),
    ))


# ---------------------------------------------------------------------------
# 考勤与请假
# ---------------------------------------------------------------------------
@require_GET
@student_only
def attendance(request):
    account = request.user
    overview = svc.attendance_overview(account)
    scope = request.GET.get('scope', 'all')
    leaves = overview['leaves']
    if scope == 'pending':
        leaves = [item for item in leaves if item.status == 'submitted']
    return render(request, 'workspace/student/attendance.html', _ctx(
        request,
        overview=overview,
        leaves=leaves,
        scope=scope,
        leave_types=_leave_types(),
    ))


def _leave_types():
    from smass_attendance.models import LEAVE_TYPES

    return LEAVE_TYPES


@require_POST
@student_only
def leave_submit(request):
    from smass_attendance import services as attendance_services
    from smass_attendance.services import AttendanceError

    record_obj = svc.student_record(request.user)
    try:
        attendance_services.submit_leave(
            record_obj,
            request.POST.get('leave_type', ''),
            parse_date(request.POST.get('start_date', '') or ''),
            parse_date(request.POST.get('end_date', '') or ''),
            request.POST.get('reason', ''),
            request.user,
        )
        messages.success(request, '请假申请已提交，等待审批。')
    except (AttendanceError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/attendance/')


@require_POST
@student_only
def leave_cancel(request, pk):
    from smass_attendance import services as attendance_services
    from smass_attendance.services import AttendanceError

    from smass_attendance.models import LeaveRequest

    leave = LeaveRequest.objects.filter(pk=pk).first()
    if leave is None:
        messages.error(request, '请假申请不存在。')
        return redirect('/student/attendance/')
    try:
        attendance_services.cancel_leave(leave, request.user)
        messages.success(request, '请假申请已撤销。')
    except (AttendanceError, PermissionError) as exc:
        messages.error(request, str(exc) or '当前状态不能撤销。')
    return redirect('/student/attendance/')


# ---------------------------------------------------------------------------
# 费用
# ---------------------------------------------------------------------------
@require_GET
@student_only
def fees(request):
    account = request.user
    bills = svc.bills_of(account)
    return render(request, 'workspace/student/fees.html', _ctx(
        request,
        bills=bills,
        summary=svc.bill_summary(bills),
    ))


@require_POST
@student_only
def fee_pay(request, pk):
    from smass_finance import services as finance_services
    from smass_finance.models import Bill
    from smass_finance.services import FinanceError

    bill = Bill.objects.filter(pk=pk).first()
    if bill is None:
        messages.error(request, '账单不存在。')
        return redirect('/student/fees/')
    due = bill.total - bill.paid
    try:
        finance_services.pay_bill(bill, due, request.user,
                                  note='学生工作台自助缴费')
        messages.success(request, '缴费已登记，账单状态已更新。')
    except (FinanceError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/fees/')


# ---------------------------------------------------------------------------
# 场地预约
# ---------------------------------------------------------------------------
@require_GET
@student_only
def bookings(request):
    from smass_facilities.models import Room

    account = request.user
    rooms = list(Room.objects.filter(is_active=True, status='open')
                 .select_related('building').order_by('building__name', 'code'))
    return render(request, 'workspace/student/bookings.html', _ctx(
        request,
        rooms=rooms,
        bookings=svc.bookings_of(account),
        now=timezone.localtime(),
    ))


@require_POST
@student_only
def booking_create(request):
    from smass_facilities import services as facility_services
    from smass_facilities.models import Room
    from smass_facilities.services import BookingError

    room = Room.objects.filter(pk=request.POST.get('room') or 0).first()
    start_at = parse_datetime(request.POST.get('start_at', '') or '')
    end_at = parse_datetime(request.POST.get('end_at', '') or '')
    if room is None:
        messages.error(request, '请选择有效的场地。')
        return redirect('/student/bookings/')
    if start_at is None or end_at is None:
        messages.error(request, '请填写完整的开始与结束时间。')
        return redirect('/student/bookings/')
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at)
    if timezone.is_naive(end_at):
        end_at = timezone.make_aware(end_at)
    try:
        facility_services.create_booking(
            request.user, room, start_at, end_at,
            request.POST.get('purpose', ''),
            attendees=int(request.POST.get('attendees') or 0),
        )
        messages.success(request, '预约申请已提交。')
    except (FacilityError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/bookings/')


@require_POST
@student_only
def booking_cancel(request, pk):
    from smass_facilities import services as facility_services
    from smass_facilities.models import RoomBooking
    from smass_facilities.services import BookingError

    booking = RoomBooking.objects.filter(pk=pk).first()
    if booking is None:
        messages.error(request, '预约不存在。')
        return redirect('/student/bookings/')
    try:
        facility_services.cancel_booking(
            booking, request.user, request.POST.get('reason', '') or '本人取消')
        messages.success(request, '预约已取消。')
    except (FacilityError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/bookings/')


# ---------------------------------------------------------------------------
# 活动与志愿
# ---------------------------------------------------------------------------
@require_GET
@student_only
def activities(request):
    account = request.user
    overview = svc.activities_overview(account)
    now = timezone.now()
    items = []
    for activity in overview['upcoming']:
        registration = overview['registrations'].get(activity.id)
        can_register = (
            registration is None
            and activity.start_at > now
            and (activity.registration_deadline is None
                 or activity.registration_deadline >= now)
        )
        items.append({
            'activity': activity,
            'registration': registration,
            'can_register': can_register,
            'deadline_passed': bool(activity.registration_deadline)
            and activity.registration_deadline < now,
        })
    my_registrations = sorted(
        overview['registrations'].values(),
        key=lambda item: item.registered_at, reverse=True)
    return render(request, 'workspace/student/activities.html', _ctx(
        request,
        overview=overview,
        items=items,
        my_registrations=my_registrations,
        volunteer=svc.volunteer_summary(account),
        now=now,
    ))


@require_POST
@student_only
def activity_register(request, pk):
    from smass_activities import services as activity_services
    from smass_activities.models import Activity
    from smass_activities.services import ActivityError

    activity = Activity.objects.filter(pk=pk).first()
    record_obj = svc.student_record(request.user)
    if activity is None:
        messages.error(request, '活动不存在。')
        return redirect('/student/activities/')
    try:
        activity_services.register(activity, record_obj, request.user)
        messages.success(request, '报名成功。')
    except (ActivityError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/activities/')


@require_POST
@student_only
def activity_cancel(request, pk):
    from smass_activities import services as activity_services
    from smass_activities.models import ActivityRegistration
    from smass_activities.services import ActivityError

    registration = ActivityRegistration.objects.filter(pk=pk).first()
    if registration is None:
        messages.error(request, '报名记录不存在。')
        return redirect('/student/activities/')
    try:
        activity_services.cancel_registration(registration, request.user)
        messages.success(request, '报名已取消。')
    except (ActivityError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/activities/')


@require_GET
@student_only
def volunteer(request):
    return render(request, 'workspace/student/volunteer.html', _ctx(
        request,
        summary=svc.volunteer_summary(request.user),
    ))


# ---------------------------------------------------------------------------
# 社团 / 学生组织
# ---------------------------------------------------------------------------
@require_GET
@student_only
def clubs(request):
    overview = svc.clubs_overview(request.user)
    rows = [{'club': club,
             'membership': overview['memberships'].get(club.id),
             'post': overview['posts'].get(club.id)}
            for club in overview['clubs']]
    return render(request, 'workspace/student/clubs.html', _ctx(
        request,
        overview=overview,
        rows=rows,
    ))


@require_POST
@student_only
def club_apply(request, pk):
    from smass_clubs import services as club_services
    from smass_clubs.models import Club
    from smass_clubs.services import ClubError

    club = Club.objects.filter(pk=pk).first()
    record_obj = svc.student_record(request.user)
    if club is None:
        messages.error(request, '社团不存在。')
        return redirect('/student/clubs/')
    try:
        club_services.apply_join(club, record_obj, request.user)
        messages.success(request, '入社申请已提交。')
    except (ClubError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/student/clubs/')


@require_GET
@student_only
def organizations(request):
    return render(request, 'workspace/student/organizations.html', _ctx(
        request,
        overview=svc.organizations_overview(request.user),
        chain=svc.record_chain(svc.student_record(request.user)),
    ))


# ---------------------------------------------------------------------------
# 寝室 / 通知
# ---------------------------------------------------------------------------
@require_GET
@student_only
def dormitory(request):
    record_obj = svc.student_record(request.user)
    return render(request, 'workspace/student/dormitory.html', _ctx(
        request,
        dormitory=svc.dormitory_of(record_obj),
        record=record_obj,
        chain=svc.record_chain(record_obj),
    ))


@require_GET
@student_only
def notices(request):
    from smass_forum.models import Announcement

    items = svc.announcements_for('student', limit=40)
    return render(request, 'workspace/student/notices.html', _ctx(
        request,
        notices=items,
        total=len(items),
    ))
