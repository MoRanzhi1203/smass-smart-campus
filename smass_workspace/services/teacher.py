"""教师端数据聚合（含辅导员扩展范围）。"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from . import student as student_svc


def my_sections(account):
    from smass_academic.models import TeachingAssignment

    if account is None or not getattr(account, 'is_authenticated', False):
        return []
    assignments = (TeachingAssignment.objects
                   .filter(account=account, revoked_at__isnull=True)
                   .select_related('section', 'section__course', 'section__term',
                                   'section__term__year')
                   .order_by('section__term__year__start_date',
                             'section__course__title'))
    return [item.section for item in assignments]


def section_students(sections):
    from smass_academic.models import Enrollment

    ids = [section.pk for section in sections]
    return list(
        Enrollment.objects.filter(section_id__in=ids)
        .exclude(status='dropped')
        .select_related('account', 'account__student_profile', 'section',
                        'section__course')
        .order_by('section__course__title', 'account__display_name'))


def my_students(account):
    """本人教学班内的学生（去重）。"""
    from smass_organization.models import StudentRecord

    enrollments = section_students(my_sections(account))
    account_ids = [item.account_id for item in enrollments]
    return list(
        StudentRecord.objects.filter(account_id__in=account_ids)
        .select_related('unit', 'unit__parent')
        .order_by('unit__name', 'student_no'))


def student_section_map(account):
    """学生账号 → 其所在教学班名称，供学生事务列表展示。"""
    mapping = {}
    for enrollment in section_students(my_sections(account)):
        mapping.setdefault(enrollment.account_id, []).append(
            '{} {}'.format(enrollment.section.course.title,
                           enrollment.section.code))
    return mapping


def my_entries(account, run=None):
    from smass_scheduling.models import ScheduleEntry

    run = run or student_svc.published_run()
    if run is None:
        return []
    return list(
        ScheduleEntry.objects.filter(run=run, teacher=account)
        .select_related('requirement', 'requirement__section',
                        'requirement__section__course', 'room',
                        'room__building', 'teacher', 'cohort')
        .order_by('weekday', 'period'))


def weekly_load(entries):
    """本周课时（同一教学班同一时段合并计 1 节）。"""
    return len(entries)


def attendance_sessions(account, limit=40):
    from smass_attendance.models import AttendanceSession

    classes = my_classes(account)
    condition = Q(created_by=account.login_name)
    if classes:
        condition |= Q(unit__in=classes)
    return list(
        AttendanceSession.objects.filter(condition)
        .select_related('unit')
        .order_by('-session_date', '-id')[:limit])


def my_classes(account):
    """本人教学班学生所在的班级组织（去重）。"""
    from smass_organization.models import OrganizationUnit

    students = my_students(account)
    unit_ids = [item.unit_id for item in students if item.unit_id]
    if not unit_ids:
        return OrganizationUnit.objects.none()
    return OrganizationUnit.objects.filter(pk__in=set(unit_ids))


def pending_leaves(account):
    from smass_attendance.models import LEAVE_SUBMITTED, LeaveRequest

    students = my_students(account)
    if not students:
        return []
    return list(
        LeaveRequest.objects.filter(
            record__in=students, status=LEAVE_SUBMITTED)
        .select_related('record', 'record__unit')
        .order_by('-created_at'))


def leave_history(account, limit=40):
    from smass_attendance.models import LeaveRequest

    students = my_students(account)
    if not students:
        return []
    return list(
        LeaveRequest.objects.filter(record__in=students)
        .select_related('record', 'record__unit')
        .order_by('-created_at')[:limit])


def pending_makeups(account):
    from smass_attendance.models import MAKEUP_SUBMITTED, MakeupRequest

    students = my_students(account)
    if not students:
        return []
    return list(
        MakeupRequest.objects.filter(
            record__in=students, status=MAKEUP_SUBMITTED)
        .select_related('record', 'session')
        .order_by('-created_at'))


def pending_tasks(account, limit=20):
    from smass_workflow.models import ApprovalTask

    return list(
        ApprovalTask.objects.filter(
            assignee=account.login_name, status='pending')
        .select_related('instance', 'node')
        .order_by('-created_at')[:limit])


def pending_bookings(account, limit=20):
    """教师可审批的场地预约（需要审批且待处理）。"""
    from smass_facilities.models import RoomBooking
    from smass_facilities.services import can_approve

    if not can_approve(account):
        return []
    return list(
        RoomBooking.objects.filter(status='pending')
        .select_related('room', 'room__building', 'account')
        .order_by('start_at')[:limit])


def counselor_overview(account):
    """辅导员视图：负责班级、学生、待审批请假。"""
    from .. import permissions as perms

    if not perms.is_counselor(account):
        return None
    classes = list(perms.counselor_classes(account))
    students = list(perms.counselor_students(account).select_related('unit'))
    from smass_attendance.models import LEAVE_SUBMITTED, LeaveRequest

    pending = []
    if students:
        pending = list(
            LeaveRequest.objects.filter(
                record__in=students, status=LEAVE_SUBMITTED)
            .select_related('record', 'record__unit')
            .order_by('-created_at'))
    return {
        'classes': classes,
        'students': students,
        'pending_leaves': pending,
        'class_count': len(classes),
        'student_count': len(students),
    }


def notices(account, limit=20):
    return student_svc.announcements_for('teacher', limit=limit)


def overview(account):
    sections = my_sections(account)
    students = my_students(account)
    entries = my_entries(account)
    leaves = pending_leaves(account)
    tasks = pending_tasks(account)
    counselor = counselor_overview(account)
    enrollments = section_students(sections)
    counts = {}
    for item in enrollments:
        counts[item.section_id] = counts.get(item.section_id, 0) + 1
    section_rows = [{'section': section,
                     'students': counts.get(section.pk, 0)}
                    for section in sections]
    return {
        'sections': section_rows,
        'section_count': len(sections),
        'students': students,
        'student_count': len(students),
        'entries': entries,
        'today': [entry for entry in entries
                  if entry.weekday == student_svc.today_index()],
        'pending_leaves': leaves,
        'pending_leave_count': len(leaves),
        'pending_tasks': tasks,
        'pending_task_count': len(tasks),
        'counselor': counselor,
        'term': student_svc.current_term(),
        'run': student_svc.published_run(),
        'notices': notices(account, limit=6),
    }
