"""教师工作台视图（含辅导员扩展）。

对象级范围由 ``permissions.scoped_student_records`` 统一判定：
教师看任课教学班学生；辅导员在此基础上叠加负责班级学生（并集），
列表、详情、审批共用同一范围。
"""
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .. import permissions as perms
from ..services import student as student_svc
from ..services import teacher as svc

teacher_only = perms.require_kind(perms.KIND_TEACHER)


def _ctx(request, **extra):
    base = {'workspace_kind': perms.KIND_TEACHER}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def home(request):
    data = svc.overview(request.user)
    classes = list(svc.my_classes(request.user))
    return render(request, 'workspace/teacher/home.html', _ctx(
        request,
        **data,
        classes=classes,
        period_grid=student_svc.grid_rows(
            data['entries'], student_svc.week_span(data['entries'])),
        periods=range(1, student_svc.week_span(data['entries']) + 1),
        today_index=student_svc.today_index(),
    ))


# ---------------------------------------------------------------------------
# 教学
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def courses(request):
    sections = svc.my_sections(request.user)
    enrollments = svc.section_students(sections)
    counts = {}
    for item in enrollments:
        counts[item.section_id] = counts.get(item.section_id, 0) + 1
    rows = [{'section': section, 'students': counts.get(section.pk, 0)}
            for section in sections]
    return render(request, 'workspace/teacher/courses.html', _ctx(
        request,
        rows=rows,
        section_count=len(sections),
        term=student_svc.current_term(),
    ))


@require_GET
@teacher_only
def sections(request):
    sections_list = svc.my_sections(request.user)
    enrollments = svc.section_students(sections_list)
    grouped = {}
    for item in enrollments:
        grouped.setdefault(item.section_id, []).append(item)
    rows = [{'section': section,
             'enrollments': grouped.get(section.pk, []),
             'count': len(grouped.get(section.pk, []))}
            for section in sections_list]
    return render(request, 'workspace/teacher/sections.html', _ctx(
        request,
        rows=rows,
        term=student_svc.current_term(),
    ))


@require_GET
@teacher_only
def timetable(request):
    entries = svc.my_entries(request.user)
    term = student_svc.current_term()
    current = min(student_svc.current_teaching_week(term), 20)
    raw_week = request.GET.get('week', '')
    week = int(raw_week) if raw_week.isdigit() else current
    week = max(1, min(week, 20))
    week_entries = student_svc.entries_for_week(entries, week)
    periods = student_svc.week_span(week_entries)
    from django.utils import timezone

    from smass_academic.models import TeachingAssignment
    from smass_scheduling.services import exceptions_for_sections

    section_ids = list(
        TeachingAssignment.objects
        .filter(account=request.user, revoked_at__isnull=True)
        .values_list('section_id', flat=True))
    today_exceptions = exceptions_for_sections(
        section_ids, timezone.localdate())
    return render(request, 'workspace/teacher/timetable.html', _ctx(
        request,
        entries=week_entries,
        week=week,
        current_week=current,
        weeks=range(1, 21),
        today_exceptions=today_exceptions,
        rows=student_svc.grid_rows(week_entries, periods),
        periods=range(1, periods + 1),
        today=student_svc.today_index(),
        term=term,
        run=student_svc.published_run(),
    ))


# ---------------------------------------------------------------------------
# 考勤管理
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def attendance(request):
    classes = list(svc.my_classes(request.user))
    sessions = svc.attendance_sessions(request.user)
    return render(request, 'workspace/teacher/attendance.html', _ctx(
        request,
        classes=classes,
        sessions=sessions,
        today=timezone.localdate(),
        periods=('第1-2节', '第3-4节', '第5-6节', '第7-8节', '第9-10节'),
    ))


@require_POST
@teacher_only
def attendance_create(request):
    from smass_attendance import services as attendance_services
    from smass_attendance.services import AttendanceError
    from smass_organization.models import OrganizationUnit

    unit = OrganizationUnit.objects.filter(
        pk=request.POST.get('unit') or 0).first()
    if unit is None:
        messages.error(request, '请选择考勤班级。')
        return redirect('/teacher/attendance/')
    try:
        session = attendance_services.create_session(
            unit,
            parse_date(request.POST.get('session_date', '') or '')
            or timezone.localdate(),
            request.POST.get('period', '第1-2节'),
            request.user,
            topic=request.POST.get('topic', ''),
        )
        messages.success(request, '考勤场次已创建，签到码：{}'.format(session.code))
    except AttendanceError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权发起考勤。')
    return redirect('/teacher/attendance/')


@require_GET
@teacher_only
def attendance_detail(request, pk):
    from smass_attendance.models import AttendanceSession, AttendanceRecord
    from smass_organization.models import StudentRecord

    session = AttendanceSession.objects.filter(pk=pk).select_related('unit').first()
    if session is None:
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '考勤场次',
            'detail': '考勤场次不存在。',
            'landing_url': perms.landing_url(request.user),
        }, status=404)

    # 对象级校验：只能管理本人发起，或本人学生所在班级的场次
    my_class_ids = set(svc.my_classes(request.user).values_list('pk', flat=True))
    if session.created_by != request.user.login_name \
            and session.unit_id not in my_class_ids:
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '该考勤场次',
            'detail': '该考勤场次不属于你的教学班或负责班级。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)

    students = list(StudentRecord.objects.filter(unit=session.unit)
                    .select_related('unit').order_by('student_no'))
    records = {item.record_id: item for item in
               AttendanceRecord.objects.filter(session=session)}
    rows = [{'student': student, 'record': records.get(student.pk)}
            for student in students]
    return render(request, 'workspace/teacher/attendance_detail.html', _ctx(
        request,
        session=session,
        rows=rows,
        statuses=('present', 'late', 'absent', 'leave'),
    ))


@require_POST
@teacher_only
def attendance_mark(request, pk):
    from smass_attendance import services as attendance_services
    from smass_attendance.models import AttendanceSession
    from smass_attendance.services import AttendanceError
    from smass_organization.models import StudentRecord

    session = AttendanceSession.objects.filter(pk=pk).first()
    student = StudentRecord.objects.filter(
        pk=request.POST.get('record') or 0).first()
    if session is None or student is None:
        messages.error(request, '考勤场次或学生不存在。')
        return redirect('/teacher/attendance/')
    try:
        attendance_services.teacher_mark(
            session, student, request.POST.get('status', 'present'),
            request.user, note=request.POST.get('note', ''))
        messages.success(request, '考勤状态已更新。')
    except AttendanceError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权登记该考勤。')
    return redirect('/teacher/attendance/{}/'.format(pk))


@require_POST
@teacher_only
def attendance_bulk_mark(request, pk):
    from django.db import transaction

    from smass_attendance import services as attendance_services
    from smass_attendance.models import AttendanceSession
    from smass_attendance.services import AttendanceError
    from smass_organization.models import StudentRecord

    session = AttendanceSession.objects.filter(pk=pk).first()
    if session is None:
        messages.error(request, '考勤场次不存在。')
        return redirect('/teacher/attendance/')
    my_class_ids = set(svc.my_classes(request.user).values_list('pk', flat=True))
    if session.created_by != request.user.login_name \
            and session.unit_id not in my_class_ids:
        messages.error(request, '当前账号无权登记该考勤。')
        return redirect('/teacher/attendance/')

    students = StudentRecord.objects.filter(unit=session.unit)
    updated = 0
    try:
        with transaction.atomic():
            for student in students:
                status = (request.POST.get(
                    'status_{}'.format(student.pk)) or '').strip()
                if status not in ('present', 'late', 'absent', 'leave'):
                    continue
                attendance_services.teacher_mark(
                    session, student, status, request.user)
                updated += 1
        messages.success(request, '已批量登记 {} 人。'.format(updated))
    except (AttendanceError, PermissionError) as exc:
        messages.error(request, '批量登记失败：{}'.format(exc))
    return redirect('/teacher/attendance/{}/'.format(pk))


@require_POST
@teacher_only
def attendance_close(request, pk):
    from smass_attendance import services as attendance_services
    from smass_attendance.models import AttendanceSession
    from smass_attendance.services import AttendanceError

    session = AttendanceSession.objects.filter(pk=pk).first()
    if session is None:
        messages.error(request, '考勤场次不存在。')
        return redirect('/teacher/attendance/')
    try:
        attendance_services.close_session(session, request.user)
        messages.success(request, '考勤已结束。')
    except AttendanceError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权结束该考勤。')
    return redirect('/teacher/attendance/{}/'.format(pk))


# ---------------------------------------------------------------------------
# 学生事务
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def students(request):
    students_list = perms.scoped_student_records(request.user).select_related(
        'unit', 'unit__parent').order_by('student_no')
    section_map = svc.student_section_map(request.user)
    rows = [{'student': student,
             'sections': section_map.get(student.account_id, [])}
            for student in students_list]
    return render(request, 'workspace/teacher/students.html', _ctx(
        request,
        rows=rows,
        student_count=len(rows),
        is_counselor=perms.is_counselor(request.user),
        counselor=svc.counselor_overview(request.user),
    ))


@require_GET
@teacher_only
def student_detail(request, pk):
    from smass_organization.models import StudentRecord
    from smass_attendance.models import AttendanceRecord, LeaveRequest

    student = StudentRecord.objects.filter(pk=pk).select_related(
        'unit', 'unit__parent', 'unit__parent__parent').first()
    if student is None or not perms.can_access_student(request.user, student):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '该学生档案',
            'detail': '该学生不在你的教学班或负责班级范围内。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)

    attendance_records = list(
        AttendanceRecord.objects.filter(record=student)
        .select_related('session').order_by('-session__session_date')[:15])
    leaves = list(LeaveRequest.objects.filter(record=student)
                  .order_by('-created_at')[:10])
    from smass_academic.models import Enrollment

    enrollments = list(
        Enrollment.objects.filter(account_id=student.account_id)
        .exclude(status='dropped')
        .select_related('section', 'section__course'))
    return render(request, 'workspace/teacher/student_detail.html', _ctx(
        request,
        student=student,
        attendance=attendance_records,
        leaves=leaves,
        enrollments=enrollments,
    ))


# ---------------------------------------------------------------------------
# 审批中心
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def approvals(request):
    return render(request, 'workspace/teacher/approvals.html', _ctx(
        request,
        leaves=svc.pending_leaves(request.user),
        makeups=svc.pending_makeups(request.user),
        tasks=svc.pending_tasks(request.user),
        bookings=svc.pending_bookings(request.user),
        history=svc.leave_history(request.user, limit=15),
        can_approve_booking=bool(svc.pending_bookings(request.user)) or
        _can_approve_facilities(request.user),
    ))


def _can_approve_facilities(account):
    from smass_facilities.services import can_approve

    return can_approve(account)


@require_POST
@teacher_only
def leave_action(request, pk, action):
    from smass_attendance import services as attendance_services
    from smass_attendance.models import LeaveRequest
    from smass_attendance.services import AttendanceError

    leave = LeaveRequest.objects.filter(pk=pk).first()
    if leave is None:
        messages.error(request, '请假申请不存在。')
        return redirect('/teacher/approvals/')
    try:
        if action == 'approve':
            attendance_services.approve_leave(leave, request.user)
            messages.success(request, '请假已批准，学生端状态已同步。')
        elif action == 'reject':
            attendance_services.reject_leave(
                leave, request.user, request.POST.get('reason', '') or '不符合请假规定')
            messages.success(request, '请假已驳回，学生端状态已同步。')
        else:
            messages.error(request, '未知操作。')
    except AttendanceError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权审批该申请。')
    return redirect(request.POST.get('next') or '/teacher/approvals/')


@require_POST
@teacher_only
def makeup_action(request, pk, action):
    from smass_attendance import services as attendance_services
    from smass_attendance.models import MakeupRequest
    from smass_attendance.services import AttendanceError

    makeup = MakeupRequest.objects.filter(pk=pk).first()
    if makeup is None:
        messages.error(request, '补签申请不存在。')
        return redirect('/teacher/approvals/')
    try:
        if action == 'approve':
            attendance_services.approve_makeup(makeup, request.user)
            messages.success(request, '补签已批准。')
        elif action == 'reject':
            attendance_services.reject_makeup(
                makeup, request.user, request.POST.get('reason', '') or '不符合补签规定')
            messages.success(request, '补签已驳回。')
        else:
            messages.error(request, '未知操作。')
    except AttendanceError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权处理该申请。')
    return redirect('/teacher/approvals/')


@require_POST
@teacher_only
def task_complete(request, pk):
    from smass_workflow import services as workflow_services
    from smass_workflow.models import ApprovalTask

    task = ApprovalTask.objects.filter(pk=pk).first()
    if task is None or task.assignee != request.user.login_name:
        messages.error(request, '待办任务不存在或不属于你。')
        return redirect('/teacher/approvals/')
    try:
        workflow_services.complete_task(task, actor=request.user.login_name)
        messages.success(request, '待办已完成。')
    except workflow_services.ConflictError as exc:
        messages.warning(request, str(exc))
    return redirect('/teacher/approvals/')


@require_POST
@teacher_only
def booking_action(request, pk, action):
    from smass_facilities import services as facility_services
    from smass_facilities.models import RoomBooking
    from smass_facilities.services import FacilityError

    booking = RoomBooking.objects.filter(pk=pk).first()
    if booking is None:
        messages.error(request, '预约不存在。')
        return redirect('/teacher/approvals/')
    try:
        if action == 'approve':
            facility_services.approve_booking(booking, request.user)
            messages.success(request, '预约已批准。')
        elif action == 'reject':
            facility_services.reject_booking(
                booking, request.user, request.POST.get('reason', '') or '场地不可用')
            messages.success(request, '预约已驳回。')
        else:
            messages.error(request, '未知操作。')
    except (FacilityError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect('/teacher/approvals/')


# ---------------------------------------------------------------------------
# 辅导员
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def classes(request):
    from .. import permissions as perms_module

    if not perms_module.is_counselor(request.user):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '负责班级',
            'detail': '当前账号未被授予辅导员组织关系。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    classes_list = list(perms_module.counselor_classes(request.user))
    rows = []
    for unit in classes_list:
        rows.append({
            'unit': unit,
            'students': list(perms_module.counselor_students(request.user)
                             .filter(unit=unit).select_related('account')),
        })
    return render(request, 'workspace/teacher/classes.html', _ctx(
        request,
        rows=rows,
        class_count=len(rows),
    ))


@require_GET
@teacher_only
def counselor_students(request):
    if not perms.is_counselor(request.user):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '负责学生',
            'detail': '当前账号未被授予辅导员组织关系。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    students_list = list(perms.counselor_students(request.user)
                         .select_related('unit').order_by(
                             'unit__name', 'student_no'))
    return render(request, 'workspace/teacher/counselor_students.html', _ctx(
        request,
        students=students_list,
        student_count=len(students_list),
    ))


@require_GET
@teacher_only
def leave_review(request):
    if not perms.is_counselor(request.user):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_TEACHER,
            'attempted_label': '请假审批',
            'detail': '当前账号未被授予辅导员组织关系。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    from smass_attendance.models import LeaveRequest

    students_list = perms.counselor_students(request.user)
    leaves = list(LeaveRequest.objects.filter(record__in=students_list)
                  .select_related('record', 'record__unit')
                  .order_by('-created_at')[:60])
    pending = [item for item in leaves if item.status == 'submitted']
    return render(request, 'workspace/teacher/leave_review.html', _ctx(
        request,
        pending=pending,
        leaves=leaves,
    ))


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def notices(request):
    return render(request, 'workspace/teacher/notices.html', _ctx(
        request,
        notices=svc.notices(request.user, limit=40),
    ))


# ---------------------------------------------------------------------------
# D 增量：名单导出与班级考勤统计
# ---------------------------------------------------------------------------
@require_GET
@teacher_only
def sections_export(request):
    from smass_workspace.services import export as export_svc

    sections_list = svc.my_sections(request.user)
    enrollments = svc.section_students(sections_list)
    rows = []
    for item in enrollments:
        profile = getattr(item.account, 'student_profile', None)
        rows.append([
            getattr(profile, 'student_no', '') or item.account.login_name,
            item.account.display_name,
            item.section.course.title,
            item.section.code,
            item.get_status_display(),
        ])
    return export_svc.csv_response(
        ['学号', '姓名', '课程', '教学班', '选课状态'], rows,
        'section-students')


@require_GET
@teacher_only
def attendance_stats(request):
    from smass_attendance import services as attendance_services

    classes = list(svc.my_classes(request.user))
    stats = []
    for unit in classes:
        rows = attendance_services.unit_stats(unit)
        total = sum(row['total'] for row in rows)
        attended = sum(row['present'] + row['late'] for row in rows)
        stats.append({
            'unit': unit,
            'students': len(rows),
            'total': total,
            'attended': attended,
            'rate': round(attended * 100.0 / total, 1) if total else 0.0,
        })
    return render(request, 'workspace/teacher/attendance_stats.html', _ctx(
        request, stats=stats, classes=classes))
