"""P6 校园生活：考勤、请假、社团、活动、志愿/学分、财务、通知。

全部以已生成的学生/教师/班级为输入；按业务键 + ignore_conflicts 保证幂等。
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from r21_account.models import Account
from smass_activities.models import (
    Activity,
    ActivityCredit,
    ActivityRegistration,
)
from smass_attendance.models import AttendanceRecord, AttendanceSession, LeaveRequest
from smass_clubs.models import Club, ClubMembership, ClubPost
from smass_finance.models import Bill, BillItem, FeeItem, Payment
from smass_organization.models import OrganizationUnit, StudentRecord
from smass_workflow.models import Notification

from .rng import Rng

BATCH_SIZE = 500
SESSIONS_PER_CLASS = 2
LEAVE_COUNT = 300
CLUB_COUNT = 20
CLUB_MEMBERS = 25
ACTIVITY_COUNT = 40
ACTIVITY_SIGNUPS = 20
BILL_PAID_RATIO = 0.6
NOTICE_COUNT = 400

CLUB_CATEGORIES = ['club', 'association', 'league', 'union']
CLUB_NAMES = [
    '程序设计协会', '机器人社', '数学建模社', '电子创新社', '英语角',
    '篮球社', '足球社', '羽毛球社', '乒乓球社', '跑步俱乐部',
    '摄影社', '合唱团', '话剧社', '舞蹈社', '书法社',
    '青年志愿者协会', '环保协会', '支教团', '心理协会', '献血服务队',
]
ACTIVITY_TITLES = [
    '新生程序设计竞赛', '校园马拉松', '宿舍文化节', '志愿服务进社区',
    '英语演讲比赛', '创新创业讲座', '实验室开放日', '冬季音乐会',
]


def generate_campus_life(config, ctx, *, dry_run=False):
    students = list(StudentRecord.objects.filter(
        student_no__startswith='S').select_related('unit').order_by('student_no'))
    teachers = list(Account.objects.filter(
        login_name__startswith='sim_tea_').order_by('login_name'))
    classes = list(OrganizationUnit.objects.filter(
        code__startswith='SIM-CLS-').order_by('code'))
    if not students or not classes:
        raise ValueError('请先生成组织与学生')
    plan = {
        'attendance_sessions': len(classes) * SESSIONS_PER_CLASS,
        'attendance_records': len(classes) * SESSIONS_PER_CLASS
        * config['students_per_class'],
        'leaves': min(LEAVE_COUNT, len(students)),
        'clubs': CLUB_COUNT, 'club_members': CLUB_COUNT * CLUB_MEMBERS,
        'activities': ACTIVITY_COUNT,
        'registrations': ACTIVITY_COUNT * ACTIVITY_SIGNUPS,
        'bills': len(students), 'notifications': NOTICE_COUNT,
    }
    if dry_run:
        return dict(plan, dry_run=True)

    rng = Rng(0, 'campus')
    attendance = _attendance(classes, teachers, students, config, rng)
    leaves = _leaves(students, rng)
    clubs = _clubs(students, teachers, rng)
    activities = _activities(students, teachers, rng)
    finance = _finance(students, rng)
    notices = _notifications(students, rng)
    ctx.stage_done('campus', dict(plan))
    return dict(plan, attendance_sessions_created=attendance[0],
                attendance_records_created=attendance[1],
                leaves_created=leaves, clubs_created=clubs[0],
                members_created=clubs[1], activities_created=activities[0],
                registrations_created=activities[1],
                bills_created=finance[0], payments_created=finance[1],
                notifications_created=notices)


def _attendance(classes, teachers, students, config, rng):
    today = timezone.localdate()
    existing = set(AttendanceSession.objects.filter(
        unit__in=classes).values_list('unit_id', 'session_date', 'period'))
    pending = []
    for class_unit in classes:
        for index in range(SESSIONS_PER_CLASS):
            session_date = today - timedelta(days=3 + index * 2)
            key = (class_unit.pk, session_date, '第1-2节')
            if key in existing:
                continue
            pending.append(AttendanceSession(
                unit=class_unit, session_date=session_date,
                period='第1-2节', topic='仿真考勤',
                status='closed', created_by='simulation',
                closed_at=timezone.now()))
    created_sessions = 0
    if pending:
        AttendanceSession.objects.bulk_create(pending, batch_size=BATCH_SIZE)
        created_sessions = len(pending)

    sessions = list(AttendanceSession.objects.filter(
        unit__in=classes).order_by('unit_id', 'session_date'))
    by_class = {}
    for student in students:
        by_class.setdefault(student.unit_id, []).append(student)
    records = []
    for session in sessions:
        cohort = by_class.get(session.unit_id, [])
        for student in cohort:
            roll = rng.randint(1, 100)
            status = 'present' if roll <= 85 else ('late' if roll <= 95 else 'absent')
            records.append(AttendanceRecord(
                session=session, record=student, status=status,
                source='teacher',
                checked_at=timezone.now() if status != 'absent' else None))
        if len(records) >= BATCH_SIZE:
            AttendanceRecord.objects.bulk_create(
                records, ignore_conflicts=True, batch_size=BATCH_SIZE)
            records = []
    if records:
        AttendanceRecord.objects.bulk_create(
            records, ignore_conflicts=True, batch_size=BATCH_SIZE)
    return created_sessions, AttendanceRecord.objects.filter(
        session__unit__in=classes).count()


def _leaves(students, rng):
    LeaveRequest.objects.filter(record__student_no__startswith='S').delete()
    today = timezone.localdate()
    sample = rng.sample(students, min(LEAVE_COUNT, len(students)))
    rows = []
    for index, student in enumerate(sample):
        status = ('approved', 'submitted', 'rejected')[index % 3]
        start = today - timedelta(days=rng.randint(1, 30))
        rows.append(LeaveRequest(
            record=student, leave_type='sick' if index % 2 else 'personal',
            start_date=start, end_date=start + timedelta(days=rng.randint(1, 3)),
            reason='仿真请假申请', status=status,
            submitted_by=student.account.login_name,
            reviewed_by='sim_teacher' if status != 'submitted' else '',
            reviewed_at=timezone.now() if status != 'submitted' else None,
            reject_reason='材料不足' if status == 'rejected' else ''))
    LeaveRequest.objects.bulk_create(rows, batch_size=BATCH_SIZE)
    return len(rows)


def _clubs(students, teachers, rng):
    rows = []
    for index in range(CLUB_COUNT):
        code = 'SIM-CLUB-{:02d}'.format(index + 1)
        club, _ = Club.objects.update_or_create(
            code=code, defaults={
                'name': CLUB_NAMES[index % len(CLUB_NAMES)],
                'category': CLUB_CATEGORIES[index % len(CLUB_CATEGORIES)],
                'advisor': teachers[index % len(teachers)],
                'description': '仿真社团', 'status': 'active',
                'created_by': 'simulation'})
        rows.append(club)
    created = len(rows)
    members = 0
    for index, club in enumerate(rows):
        sample = rng.sample(students, min(CLUB_MEMBERS, len(students)))
        memberships = []
        for order, student in enumerate(sample):
            memberships.append(ClubMembership(
                club=club, record=student,
                role='leader' if order == 0 else 'member',
                status='active',
                joined_at=timezone.now(), reviewed_by='simulation',
                reviewed_at=timezone.now()))
        ClubMembership.objects.bulk_create(
            memberships, ignore_conflicts=True, batch_size=BATCH_SIZE)
        members += len(memberships)
        if sample:
            ClubPost.objects.update_or_create(
                club=club, record=sample[0], term='2025-2026',
                defaults={'title': 'president', 'status': 'active',
                          'appointed_by': 'simulation'})
    return created, members


def _activities(students, teachers, rng):
    now = timezone.now()
    rows = []
    for index in range(ACTIVITY_COUNT):
        start = now + timedelta(days=index - ACTIVITY_COUNT // 2)
        activity, _ = Activity.objects.update_or_create(
            title='{}（{}）'.format(ACTIVITY_TITLES[index % len(ACTIVITY_TITLES)],
                                   index + 1),
            defaults={
                'category': ['lecture', 'club', 'second_class', 'volunteer'][index % 4],
                'organizer': teachers[index % len(teachers)],
                'location': '仿真活动中心{}'.format(index % 5 + 1),
                'start_at': start, 'end_at': start + timedelta(hours=2),
                'registration_deadline': start - timedelta(days=1),
                'capacity': ACTIVITY_SIGNUPS + 10,
                'credit_points': Decimal('0.5') if index % 3 == 0 else Decimal('0'),
                'volunteer_hours': Decimal('2.0') if index % 4 == 1 else Decimal('0'),
                'status': 'closed' if start < now else 'published',
                'checkin_code': '{:06d}'.format(100000 + index),
                'created_by': 'simulation'})
        rows.append(activity)
    created = len(rows)
    registrations = 0
    credit_rows = []
    for index, activity in enumerate(rows):
        sample = rng.sample(students, min(ACTIVITY_SIGNUPS, len(students)))
        entries = []
        for order, student in enumerate(sample):
            status = 'checked_in' if order < len(sample) - 2 else (
                'waitlisted' if order == len(sample) - 1 else 'registered')
            entries.append(ActivityRegistration(
                activity=activity, record=student, status=status,
                checked_in_at=timezone.now() if status == 'checked_in' else None))
            if activity.status == 'closed' and order < 5 and activity.credit_points:
                credit_rows.append(ActivityCredit(
                    activity=activity, record=student,
                    category=activity.category, points=activity.credit_points,
                    hours=activity.volunteer_hours, status='approved',
                    reviewed_by='simulation', reviewed_at=timezone.now()))
        ActivityRegistration.objects.bulk_create(
            entries, ignore_conflicts=True, batch_size=BATCH_SIZE)
        registrations += len(entries)
    ActivityCredit.objects.bulk_create(
        credit_rows, ignore_conflicts=True, batch_size=BATCH_SIZE)
    return created, registrations


def _finance(students, rng):
    term = '2025-2026-1'
    items = []
    for code, name, category, amount in (
            ('SIM-FEE-TUITION', '仿真学费', 'tuition', '5200.00'),
            ('SIM-FEE-DORM', '仿真住宿费', 'dormitory', '1200.00'),
            ('SIM-FEE-BOOK', '仿真教材费', 'other', '400.00')):
        item, _ = FeeItem.objects.update_or_create(
            code=code, defaults={'name': name, 'category': category,
                                 'amount': Decimal(amount), 'term': term,
                                 'status': 'active'})
        items.append(item)
    existing = set(Bill.objects.filter(
        bill_no__startswith='BILL-').values_list('bill_no', flat=True))
    new_bills = []
    for student in students:
        bill_no = 'BILL-{}'.format(student.student_no)
        if bill_no in existing:
            continue
        new_bills.append(Bill(
            bill_no=bill_no, record=student, term=term,
            total=Decimal('6800.00'), paid=Decimal('0.00'),
            status='unpaid', due_date=timezone.localdate() + timedelta(days=30)))
    Bill.objects.bulk_create(new_bills, ignore_conflicts=True,
                             batch_size=BATCH_SIZE)
    bills = list(Bill.objects.filter(
        bill_no__startswith='BILL-').select_related('record'))
    bill_items = []
    for bill in bills:
        for item in items:
            bill_items.append(BillItem(bill=bill, fee_item=item,
                                       amount=item.amount))
    BillItem.objects.bulk_create(bill_items, ignore_conflicts=True,
                                 batch_size=BATCH_SIZE)
    paid_existing = set(Payment.objects.filter(
        reference__startswith='PAY-').values_list('reference', flat=True))
    payments = []
    for index, bill in enumerate(bills):
        if rng.randint(1, 100) > BILL_PAID_RATIO * 100:
            continue
        reference = 'PAY-{}'.format(bill.record.student_no)
        if reference in paid_existing:
            continue
        payments.append(Payment(
            bill=bill, amount=bill.total, method='synthetic_bank',
            status='success', reference=reference, operator='simulation'))
    Payment.objects.bulk_create(payments, ignore_conflicts=True,
                                batch_size=BATCH_SIZE)
    _refresh_bills(bills)
    return len(new_bills), len(payments)


def _refresh_bills(bills):
    from django.db.models import Sum

    paid_map = dict(Payment.objects.filter(
        bill__in=bills, status='success')
        .values('bill_id').annotate(total=Sum('amount'))
        .values_list('bill_id', 'total'))
    for bill in bills:
        paid = paid_map.get(bill.pk, Decimal('0.00'))
        bill.paid = paid
        if paid <= 0:
            bill.status = 'unpaid'
        elif paid < bill.total:
            bill.status = 'partial'
        else:
            bill.status = 'paid'
    Bill.objects.bulk_update(bills, ['paid', 'status'], batch_size=BATCH_SIZE)


def _notifications(students, rng):
    existing = set(Notification.objects.filter(
        event_key__startswith='sim:').values_list('event_key', flat=True))
    sample = rng.sample(students, min(NOTICE_COUNT, len(students)))
    rows = []
    for index, student in enumerate(sample):
        key = 'sim:notice:{}'.format(index)
        if key in existing:
            continue
        rows.append(Notification(
            recipient=student.account.login_name,
            recipient_account=student.account,
            title='仿真通知 {}'.format(index + 1),
            body='这是仿真生成的站内通知，用于验证通知中心与已读流程。',
            level='info', event_key=key))
    Notification.objects.bulk_create(rows, ignore_conflicts=True,
                                     batch_size=BATCH_SIZE)
    return len(rows)
