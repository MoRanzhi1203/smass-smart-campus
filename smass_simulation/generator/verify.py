"""P7 完整性校验与分布报告：跨模型约束 + 分布统计 + 失败样本。

    python manage.py seed_campus --verify --settings=smass.settings_simulation
"""
from __future__ import annotations

from collections import Counter

from django.db.models import Count, F, Q, Sum

from r21_account.models import Account, StudentProfile, TeacherProfile
from smass_activities.models import Activity, ActivityRegistration
from smass_attendance.models import AttendanceRecord, LeaveRequest
from smass_clubs.models import Club, ClubMembership, ClubPost
from smass_dormitory.models import Bed, DormAssignment, DormBuilding, DormRoom
from smass_finance.models import Bill, Payment
from smass_organization.models import (
    OrganizationMembership,
    OrganizationUnit,
    StudentRecord,
)
from smass_academic.models import Enrollment, TeachingAssignment, TeachingSection
from smass_scheduling.models import RUN_PUBLISHED, ScheduleRun
from smass_workflow.models import Notification

STUDENT_PREFIX = 'S'
CLASS_PREFIX = 'SIM-CLS-'
SECTION_PREFIX = 'SEC-'
BATCH_SIZE = 200


def _student_set():
    return StudentRecord.objects.filter(student_no__startswith=STUDENT_PREFIX)


def run_verify():
    checks = []

    def check(name, passed, expected, actual, samples=None):
        checks.append({'name': name, 'passed': bool(passed),
                       'expected': expected, 'actual': actual,
                       'samples': samples or []})

    students = _student_set()
    student_count = students.count()
    profile_count = StudentProfile.objects.filter(
        student_no__startswith=STUDENT_PREFIX).count()
    account_count = Account.objects.filter(
        login_name__startswith='sim_stu_').count()
    check('student_triplet', student_count == profile_count == account_count,
          {'students': student_count},
          {'profiles': profile_count, 'accounts': account_count})

    classes = OrganizationUnit.objects.filter(code__startswith=CLASS_PREFIX)
    bad_class = classes.exclude(parent__unit_type='major').count()
    check('class_parent_is_major', bad_class == 0, 0, bad_class,
          list(classes.exclude(parent__unit_type='major').values_list(
              'code', flat=True)[:5]))

    sections = TeachingSection.objects.filter(code__startswith=SECTION_PREFIX)
    assigned = sets_of(TeachingAssignment.objects.filter(
        section__code__startswith=SECTION_PREFIX).values_list(
            'section_id', flat=True))
    no_teacher = [pk for pk in sections.values_list('pk', flat=True)
                  if pk not in assigned]
    check('section_has_teacher', not no_teacher, 0, len(no_teacher),
          no_teacher[:5])

    enroll_counts = dict(
        Enrollment.objects.filter(section__code__startswith=SECTION_PREFIX)
        .values('section_id').annotate(total=Count('id'))
        .values_list('section_id', 'total'))
    over_capacity = []
    for section in sections.values('pk', 'capacity'):
        if enroll_counts.get(section['pk'], 0) > section['capacity']:
            over_capacity.append(section['pk'])
    check('enrollment_within_capacity', not over_capacity, 0,
          len(over_capacity), over_capacity[:5])

    runs = ScheduleRun.objects.all()
    conflicts = sum(run.hard_conflicts for run in runs)
    latest = runs.order_by('-pk').first()
    check('schedule_no_conflicts', conflicts == 0, 0, conflicts,
          [latest.pk] if latest else [])

    head_links = (OrganizationMembership.objects
                  .filter(role='head_teacher', unit__code__startswith=CLASS_PREFIX)
                  .values('unit_id').annotate(total=Count('id')))
    bad_head = [item['unit_id'] for item in head_links
                if item['total'] != 1]
    head_covered = head_links.count()
    class_total = classes.count()
    check('class_exactly_one_head_teacher',
          not bad_head and head_covered == class_total,
          class_total, {'covered': head_covered, 'bad': len(bad_head)},
          bad_head[:5])

    counselor_links = (OrganizationMembership.objects
                       .filter(role='counselor',
                               unit__code__startswith=CLASS_PREFIX)
                       .values('account_id').annotate(total=Count('id')))
    overload = [item['account_id'] for item in counselor_links
                if item['total'] > 8]
    check('counselor_within_8_classes', not overload, 0, len(overload),
          overload[:5])

    active = DormAssignment.objects.filter(active_slot=1)
    dup_student = (active.values('student_id').annotate(total=Count('id'))
                   .filter(total__gt=1).count())
    dup_bed = (active.values('bed_id').annotate(total=Count('id'))
               .filter(total__gt=1).count())
    check('dorm_active_unique', dup_student == 0 and dup_bed == 0,
          {'dup_student': 0, 'dup_bed': 0},
          {'dup_student': dup_student, 'dup_bed': dup_bed})

    occupied = Bed.objects.filter(status=Bed.STATUS_OCCUPIED).count()
    active_count = active.count()
    check('bed_occupied_matches_assignments', occupied == active_count,
          active_count, occupied)

    room_over = []
    per_room = dict(active.values('bed__room_id').annotate(
        total=Count('id')).values_list('bed__room_id', 'total'))
    for room in DormRoom.objects.values('pk', 'capacity'):
        if per_room.get(room['pk'], 0) > room['capacity']:
            room_over.append(room['pk'])
    check('room_within_capacity', not room_over, 0, len(room_over),
          room_over[:5])

    reg_over = []
    reg_counts = dict(
        ActivityRegistration.objects.values('activity_id')
        .annotate(total=Count('id')).values_list('activity_id', 'total'))
    for activity in Activity.objects.values('pk', 'capacity'):
        if activity['capacity'] and reg_counts.get(
                activity['pk'], 0) > activity['capacity']:
            reg_over.append(activity['pk'])
    check('activity_within_capacity', not reg_over, 0, len(reg_over),
          reg_over[:5])

    leaders = ClubMembership.objects.filter(
        role='leader', status='active')
    bad_leader = [club for club in Club.objects.values_list('pk', flat=True)
                  if not leaders.filter(club_id=club).exists()]
    check('club_has_active_leader', not bad_leader, 0, len(bad_leader),
          bad_leader[:5])

    bills = list(Bill.objects.filter(
        bill_no__startswith='BILL-').annotate(
        pay_sum=Sum('payments__amount',
                    filter=Q(payments__status='success'))))
    mismatch = [bill.bill_no for bill in bills
                if (bill.pay_sum or 0) != bill.paid]
    check('bill_paid_matches_payments', not mismatch, 0, len(mismatch),
          mismatch[:5])

    notice_orphan = Notification.objects.filter(
        event_key__startswith='sim:', recipient_account__isnull=True).count()
    check('notification_recipient_exists', notice_orphan == 0, 0,
          notice_orphan)

    status_field = LeaveRequest._meta.get_field('status')
    valid_leave = [choice[0] for choice in (status_field.choices or [])]
    bad_leave = (LeaveRequest.objects.filter(
        record__student_no__startswith=STUDENT_PREFIX)
        .exclude(status__in=valid_leave).count() if valid_leave else 0)
    check('leave_status_valid', bad_leave == 0, 0, bad_leave)

    distribution = _distribution()
    passed = sum(1 for item in checks if item['passed'])
    return {
        'checks': checks,
        'passed': passed,
        'total': len(checks),
        'pass_rate': round(passed * 100.0 / len(checks), 1) if checks else 0,
        'distribution': distribution,
    }


def sets_of(values):
    return set(values)


def _distribution():
    by_college = []
    for college in OrganizationUnit.objects.filter(
            code__startswith='SIM-COL-').order_by('code'):
        by_college.append({
            'college': college.name,
            'students': StudentRecord.objects.filter(
                student_no__startswith=STUDENT_PREFIX,
                unit__parent__parent=college).count(),
            'classes': OrganizationUnit.objects.filter(
                code__startswith=CLASS_PREFIX, parent__parent=college).count(),
        })
    by_status = list(StudentRecord.objects.filter(
        student_no__startswith=STUDENT_PREFIX).values('status').annotate(
        total=Count('id')).order_by())
    dorm = {
        'buildings': DormBuilding.objects.count(),
        'rooms': DormRoom.objects.count(),
        'beds': Bed.objects.count(),
        'occupied': Bed.objects.filter(status=Bed.STATUS_OCCUPIED).count(),
    }
    dorm['occupancy'] = (round(dorm['occupied'] * 100.0 / dorm['beds'], 1)
                         if dorm['beds'] else 0)
    finance = list(Bill.objects.filter(bill_no__startswith='BILL-')
                   .values('status').annotate(total=Count('id')).order_by())
    activities = list(Activity.objects.values('status').annotate(
        total=Count('id')).order_by())
    attendance = list(AttendanceRecord.objects.filter(
        session__unit__code__startswith=CLASS_PREFIX)
        .values('status').annotate(total=Count('id')).order_by())
    return {
        'by_college': by_college,
        'student_status': by_status,
        'dorm': dorm,
        'finance': finance,
        'activities': activities,
        'attendance': attendance,
        'teachers': TeacherProfile.objects.count(),
        'leaves': LeaveRequest.objects.filter(
            record__student_no__startswith=STUDENT_PREFIX).count(),
        'clubs': Club.objects.count(),
        'notifications': Notification.objects.filter(
            event_key__startswith='sim:').count(),
    }
