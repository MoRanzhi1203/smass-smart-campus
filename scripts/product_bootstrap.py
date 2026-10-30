#!/usr/bin/env python
"""SMASS 产品隔离环境初始化（可重复执行）。

    python scripts/product_bootstrap.py            # 重建 smass_product_dev 并灌种子数据
    python scripts/product_bootstrap.py --keep-db  # 不删库，只补数据
    python scripts/product_bootstrap.py --json out.json

安全
----
- 库名白名单 ``smass_product_dev``，**绝不指向正式库 ``smass``**；
- 全部为合成数据；演示口令来自环境变量或项目 ``.env``，仓库中不保存明文。
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = 'smass.settings_product'
DB_NAME = os.environ.get('PRODUCT_DB', 'smass_product_dev')
PASSWORD = ''


def demo_password():
    global PASSWORD
    if PASSWORD:
        return PASSWORD
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    PASSWORD = (os.environ.get('PRODUCT_DEV_PASSWORD')
                or os.environ.get('INTEGRATED_DEV_PASSWORD')
                or '')
    if not PASSWORD:
        PASSWORD = 'Dev-' + secrets.token_urlsafe(9)
    return PASSWORD


def setup_django():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.conf import settings

    return settings


def db_config():
    settings = setup_django()
    return dict(settings.DATABASES['default'])


def admin_connection(cfg):
    import pymysql

    return pymysql.connect(
        host=str(cfg['HOST'] or '127.0.0.1'), port=int(cfg['PORT'] or 3306),
        user=str(cfg['USER']), password=str(cfg['PASSWORD']),
        charset='utf8mb4', autocommit=True)


def ensure_database(cfg, recreate=False):
    connection = admin_connection(cfg)
    try:
        with connection.cursor() as cursor:
            if recreate:
                cursor.execute('DROP DATABASE IF EXISTS `{}`'.format(DB_NAME))
            cursor.execute(
                'CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4'.format(
                    DB_NAME))
    finally:
        connection.close()


def migrate():
    completed = subprocess.run(
        [sys.executable, 'manage.py', 'migrate', '--noinput',
         '--settings={}'.format(SETTINGS)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=3600)
    if completed.returncode != 0:
        raise SystemExit('migrate 失败：{}'.format(
            (completed.stderr or '').strip()[-2000:]))
    return True


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------
def seed_accounts():
    from r21_account import services as account_services
    from r21_account.models import Account, StudentProfile, TeacherProfile

    account_services.ensure_role_groups()
    password = demo_password()
    people = (
        ('dev_admin', '系统管理员', 'admin', ('system_admin',), ''),
        ('dev_college', '学院管理员', 'admin', ('college_admin',), '信息工程学院'),
        ('dev_teacher', '张明', 'teacher', ('teacher',), '信息工程学院'),
        ('dev_teacher2', '李华', 'teacher', ('teacher',), '信息工程学院'),
        ('dev_counselor', '王芳', 'teacher', ('teacher',), '信息工程学院'),
        ('dev_student', '陈晨', 'student', ('student',), '信息工程学院'),
        ('dev_student2', '刘洋', 'student', ('student',), '信息工程学院'),
        ('dev_student3', '赵敏', 'student', ('student',), '信息工程学院'),
        ('dev_student4', '孙浩', 'student', ('student',), '信息工程学院'),
    )
    for login_name, display, person_type, roles, scope in people:
        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            account = Account.objects.create_user(
                login_name, password, display_name=display,
                person_type=person_type)
        account.display_name = display
        account.person_type = person_type
        account.must_change_password = False
        account.is_staff = person_type != 'student'
        if scope:
            account.scope_college = scope
        account.save()
        for role in roles:
            account_services.grant_role(account, role, granted_by='bootstrap')

    students = (
        ('dev_student', '20240101', '陈晨', '软工2401'),
        ('dev_student2', '20240102', '刘洋', '软工2401'),
        ('dev_student3', '20240103', '赵敏', '软工2401'),
        ('dev_student4', '20240104', '孙浩', '软工2402'),
    )
    for login_name, student_no, name, classes in students:
        account = Account.objects.get(login_name=login_name)
        StudentProfile.objects.update_or_create(
            account=account,
            defaults={'student_no': student_no, 'name': name,
                      'college_name': '信息工程学院', 'classes_name': classes,
                      'phone': '1380000{}'.format(student_no[-4:])})

    teachers = (
        ('dev_teacher', 'T1001', '张明'),
        ('dev_teacher2', 'T1002', '李华'),
        ('dev_counselor', 'T1003', '王芳'),
    )
    for login_name, teacher_no, name in teachers:
        account = Account.objects.get(login_name=login_name)
        TeacherProfile.objects.update_or_create(
            account=account,
            defaults={'teacher_no': teacher_no, 'name': name,
                      'college_name': '信息工程学院',
                      'phone': '1390000{}'.format(teacher_no[-3:])})
    return {'accounts': Account.objects.count()}


def seed_organization():
    from smass_organization.models import (
        OrganizationMembership, OrganizationUnit, StudentRecord,
    )
    from smass_organization.services import create_unit

    college = OrganizationUnit.objects.filter(code='DEV-COL').first()
    if college is None:
        college = create_unit(code='DEV-COL', name='信息工程学院',
                              unit_type='college')
    se = OrganizationUnit.objects.filter(code='DEV-MAJ-SE').first()
    if se is None:
        se = create_unit(code='DEV-MAJ-SE', name='软件工程',
                         unit_type='major', parent=college)
    cs = OrganizationUnit.objects.filter(code='DEV-MAJ-CS').first()
    if cs is None:
        cs = create_unit(code='DEV-MAJ-CS', name='计算机科学与技术',
                         unit_type='major', parent=college)
    classes = {}
    for code, name, parent in (
            ('DEV-CLS-2401', '软工2401', se),
            ('DEV-CLS-2402', '软工2402', se),
            ('DEV-CLS-2403', '计科2401', cs)):
        unit = OrganizationUnit.objects.filter(code=code).first()
        if unit is None:
            unit = create_unit(code=code, name=name, unit_type='class',
                               parent=parent)
        classes[code] = unit

    for code, name in (('DEV-DEPT-STU', '学生工作部'), ('DEV-DEPT-YOUTH', '校团委')):
        unit = OrganizationUnit.objects.filter(code=code).first()
        if unit is None:
            create_unit(code=code, name=name, unit_type='department')

    from r21_account.models import Account

    mapping = (
        ('20240101', 'dev_student', 'DEV-CLS-2401'),
        ('20240102', 'dev_student2', 'DEV-CLS-2401'),
        ('20240103', 'dev_student3', 'DEV-CLS-2401'),
        ('20240104', 'dev_student4', 'DEV-CLS-2402'),
    )
    for student_no, login_name, class_code in mapping:
        account = Account.objects.get(login_name=login_name)
        unit = classes[class_code]
        dorm = {
            'building': '紫荆公寓 3 号楼',
            'room': '312',
            'bed': '2 号床',
            'roommates': ['刘洋', '赵敏'],
        }
        record, created = StudentRecord.objects.get_or_create(
            student_no=student_no,
            defaults={'name': account.display_name, 'account': account,
                      'unit': unit, 'status': 'enrolled',
                      'enrolled_at': date(2024, 9, 1), 'extra': {'dormitory': dorm}})
        if not created:
            record.account = account
            record.unit = unit
            record.name = account.display_name
            record.save(update_fields=['account', 'unit', 'name'])

    counselor = Account.objects.get(login_name='dev_counselor')
    for class_code in ('DEV-CLS-2401', 'DEV-CLS-2402'):
        OrganizationMembership.objects.get_or_create(
            account=counselor, unit=classes[class_code],
            defaults={'role': 'counselor', 'started_at': date(2024, 9, 1)})
    return {'units': OrganizationUnit.objects.count(),
            'records': StudentRecord.objects.count()}


def seed_academic():
    from r21_account.models import Account
    from smass_academic import services as academic_services
    from smass_academic.models import (
        AcademicTerm, AcademicYear, Course, Enrollment, TeachingAssignment,
        TeachingSection,
    )

    year = AcademicYear.objects.filter(code='2025-2026').first()
    if year is None:
        year = academic_services.create_year(
            '2025-2026', date(2025, 9, 1), date(2026, 8, 31))
        year.is_active = True
        year.save(update_fields=['is_active'])
    term = AcademicTerm.objects.filter(year=year, semester='1').first()
    if term is None:
        term = academic_services.create_term(
            year, '1', date(2025, 9, 1), date(2026, 1, 18))
    term.is_active = True
    term.save(update_fields=['is_active'])
    AcademicTerm.objects.exclude(pk=term.pk).update(is_active=False)

    courses = {}
    for code, title, credit, kind in (
            ('CS101', '程序设计基础', 3, '必修'),
            ('CS102', '数据结构', 4, '必修'),
            ('CS103', '大学英语', 2, '公共'),
            ('CS201', '操作系统', 3, '必修')):
        course = Course.objects.filter(code=code).first()
        if course is None:
            course = academic_services.create_course(
                code, title, credit=credit, course_type=kind)
        courses[code] = course

    sections = {}
    for key, code, course_code in (
            ('CS101-A', 'A', 'CS101'),
            ('CS102-A', 'A', 'CS102'),
            ('CS103-A', 'A', 'CS103'),
            ('CS101-B', 'B', 'CS101')):
        section = TeachingSection.objects.filter(
            term=term, course=courses[course_code], code=code).first()
        if section is None:
            section = academic_services.create_section(
                term, courses[course_code], code, capacity=40)
        sections[key] = section

    teacher_map = {
        'dev_teacher': ('CS101-A', 'CS102-A'),
        'dev_teacher2': ('CS103-A', 'CS101-B'),
    }
    for login_name, keys in teacher_map.items():
        account = Account.objects.get(login_name=login_name)
        for key in keys:
            TeachingAssignment.objects.get_or_create(
                section=sections[key], account=account,
                defaults={'assigned_by': 'bootstrap'})

    student_map = {
        'dev_student': ('CS101-A', 'CS102-A', 'CS103-A'),
        'dev_student2': ('CS101-A', 'CS102-A', 'CS103-A'),
        'dev_student3': ('CS101-A', 'CS103-A'),
        'dev_student4': ('CS101-B', 'CS103-A'),
    }
    for login_name, keys in student_map.items():
        account = Account.objects.get(login_name=login_name)
        for key in keys:
            Enrollment.objects.get_or_create(
                section=sections[key], account=account,
                defaults={'status': 'enrolled'})
    return {'term': term.pk, 'sections': len(sections),
            'enrollments': Enrollment.objects.count()}


def seed_facilities():
    from smass_facilities.models import Building, Room

    building, _ = Building.objects.get_or_create(
        code='DEV-B-A', defaults={'name': '教学楼 A 座', 'campus': '主校区'})
    rooms = {}
    for code, name, kind, capacity, approval in (
            ('A101', 'A101 多媒体教室', 'classroom', 60, False),
            ('A102', 'A102 研讨室', 'meeting', 24, True),
            ('A201', 'A201 报告厅', 'other', 180, True)):
        room, _ = Room.objects.update_or_create(
            code=code,
            defaults={'name': name, 'building': building, 'floor': '1',
                      'room_type': kind, 'capacity': capacity,
                      'status': 'open', 'requires_approval': approval,
                      'is_active': True})
        rooms[code] = room
    return rooms


def seed_scheduling(rooms):
    from r21_account.models import Account
    from smass_academic.models import AcademicTerm, TeachingSection
    from smass_scheduling.models import (
        Cohort, LessonRequirement, ScheduleEntry, ScheduleRun, TimeSlot,
    )

    for weekday in range(7):
        for period in range(1, 9):
            TimeSlot.objects.get_or_create(
                weekday=weekday, period=period,
                defaults={'start_time': time(8 + (period - 1), 0),
                          'end_time': time(8 + (period - 1), 45),
                          'label': '第{}节'.format(period)})

    term = AcademicTerm.objects.filter(is_active=True).first()
    cohort_a, _ = Cohort.objects.get_or_create(
        code='DEV-COHORT-SE2401', defaults={'name': '软工2401', 'size': 30})
    cohort_b, _ = Cohort.objects.get_or_create(
        code='DEV-COHORT-SE2402', defaults={'name': '软工2402', 'size': 28})

    run = (ScheduleRun.objects.filter(term=term, algorithm='seed-fixture')
           .order_by('-id').first())
    if run is None:
        run = ScheduleRun.objects.create(
            term=term, status='draft', algorithm='seed-fixture',
            seed=2026, placed_sessions=4, required_sessions=4,
            created_by='bootstrap')

    teacher = Account.objects.get(login_name='dev_teacher')
    teacher2 = Account.objects.get(login_name='dev_teacher2')
    sections = {
        'CS101-A': TeachingSection.objects.filter(
            term=term, course__code='CS101', code='A').first(),
        'CS102-A': TeachingSection.objects.filter(
            term=term, course__code='CS102', code='A').first(),
        'CS103-A': TeachingSection.objects.filter(
            term=term, course__code='CS103', code='A').first(),
        'CS101-B': TeachingSection.objects.filter(
            term=term, course__code='CS101', code='B').first(),
    }
    plan = (
        ('CS101-A', teacher, cohort_a, rooms['A101'], 0, 1),
        ('CS102-A', teacher, cohort_a, rooms['A102'], 2, 3),
        ('CS103-A', teacher2, cohort_a, rooms['A101'], 1, 1),
        ('CS101-B', teacher2, cohort_b, rooms['A102'], 3, 5),
    )
    created = 0
    for key, teacher_account, cohort, room, weekday, period in plan:
        section = sections[key]
        requirement, _ = LessonRequirement.objects.get_or_create(
            run=run, section=section, teacher=teacher_account, cohort=cohort,
            defaults={'weekly_sessions': 1, 'session_periods': 2,
                      'students': cohort.size, 'priority': 0})
        entry, _ = ScheduleEntry.objects.get_or_create(
            run=run, requirement=requirement, weekday=weekday, period=period,
            defaults={'room': room, 'teacher': teacher_account,
                      'cohort': cohort, 'session_index': 1})
        created += 1
    run.status = 'published'
    run.placed_sessions = created
    run.required_sessions = created
    from django.utils import timezone

    run.published_at = timezone.now()
    run.save()
    return run


def seed_attendance():
    from r21_account.models import Account
    from smass_attendance import services as attendance_services
    from smass_attendance.models import AttendanceSession, LeaveRequest
    from smass_organization.models import OrganizationUnit, StudentRecord

    unit = OrganizationUnit.objects.get(code='DEV-CLS-2401')
    teacher = Account.objects.get(login_name='dev_teacher')
    today = date.today()
    sessions = []
    for offset, period in ((2, '第1-2节'), (1, '第3-4节')):
        day = today - timedelta(days=offset)
        session = AttendanceSession.objects.filter(
            unit=unit, session_date=day, period=period).first()
        if session is None:
            session = attendance_services.create_session(
                unit, day, period, teacher, topic='课程考勤')
        sessions.append(session)

    students = list(StudentRecord.objects.filter(unit=unit))
    for session in sessions:
        if session.status != 'open':
            continue
        for index, student in enumerate(students):
            status = 'present' if index < len(students) - 1 else 'late'
            attendance_services.teacher_mark(
                session, student, status, teacher)
        attendance_services.close_session(session, teacher)

    # 一条待审批请假，供教师端/辅导员端审批
    student = students[0]
    if not LeaveRequest.objects.filter(record=student, status='submitted').exists():
        attendance_services.submit_leave(
            student, 'sick', today, today + timedelta(days=2),
            '发热就诊，附校医院诊断证明。', student.account)
    return {'sessions': len(sessions), 'leaves': LeaveRequest.objects.count()}


def seed_activities():
    from django.utils import timezone

    from r21_account.models import Account
    from smass_activities import services as activity_services
    from smass_activities.models import Activity
    from smass_organization.models import StudentRecord

    admin = Account.objects.get(login_name='dev_admin')
    student = StudentRecord.objects.get(student_no='20240101')
    now = timezone.now()
    fixtures = (
        ('程序设计竞赛校内选拔', 'second_class', 3, 0, now + timedelta(days=5)),
        ('社区图书馆志愿服务', 'volunteer', 1, 4, now + timedelta(days=7)),
        ('人工智能前沿讲座', 'lecture', 1, 0, now + timedelta(days=3)),
    )
    created = []
    for title, category, points, hours, start in fixtures:
        activity = Activity.objects.filter(title=title).first()
        if activity is None:
            activity = activity_services.create_activity(
                admin, title, category, start, start + timedelta(hours=2),
                capacity=50, credit_points=points, volunteer_hours=hours,
                location='教学楼 A 座')
            activity_services.publish_activity(activity, admin)
        created.append(activity)
    try:
        activity_services.register(created[0], student, student.account)
    except Exception:  # noqa: BLE001 - 已报名时忽略
        pass
    return {'activities': Activity.objects.count()}


def seed_clubs():
    from r21_account.models import Account
    from smass_clubs import services as club_services
    from smass_clubs.models import Club
    from smass_organization.models import StudentRecord

    admin = Account.objects.get(login_name='dev_admin')
    advisor = Account.objects.get(login_name='dev_teacher2')
    student = StudentRecord.objects.get(student_no='20240101')
    fixtures = (
        ('DEV-CLUB-VOL', '青年志愿者协会', 'association'),
        ('DEV-CLUB-PROG', '程序设计协会', 'club'),
    )
    clubs = []
    for code, name, category in fixtures:
        club = Club.objects.filter(code=code).first()
        if club is None:
            club = club_services.create_club(
                admin, code, name, category, advisor=advisor,
                description='合成演示社团')
        clubs.append(club)
    try:
        membership = club_services.apply_join(clubs[0], student, student.account)
        club_services.approve_join(membership, admin)
    except Exception:  # noqa: BLE001
        pass
    return {'clubs': Club.objects.count()}


def seed_finance():
    from datetime import date as date_cls

    from r21_account.models import Account
    from smass_finance import services as finance_services
    from smass_finance.models import Bill, FeeItem
    from smass_organization.models import StudentRecord

    student = StudentRecord.objects.get(student_no='20240101')
    admin = Account.objects.get(login_name='dev_admin')
    tuition, _ = FeeItem.objects.get_or_create(
        code='DEV-FEE-TUITION',
        defaults={'name': '2025-2026 学年学费', 'category': 'tuition',
                  'amount': 5200, 'term': '2025-2026-1'})
    dorm, _ = FeeItem.objects.get_or_create(
        code='DEV-FEE-DORM',
        defaults={'name': '2025-2026 学年住宿费', 'category': 'accommodation',
                  'amount': 1200, 'term': '2025-2026-1'})
    if not Bill.objects.filter(record=student).exists():
        bill = finance_services.create_bill(
            student, '2025-2026-1', [tuition, dorm], admin,
            due_date=date_cls(2026, 1, 31))
        finance_services.pay_bill(bill, 5200, admin, note='部分缴费')
    return {'bills': Bill.objects.count()}


def seed_forum_and_notices():
    from r21_account.models import Account
    from smass_forum import services as forum_services
    from smass_forum.models import Announcement

    admin = Account.objects.get(login_name='dev_admin')
    fixtures = (
        ('2025-2026 学年第一学期教学安排', 'all',
         '本学期教学周自 9 月 1 日开始，请同学们按课表上课。'),
        ('关于开展校园志愿服务的通知', 'student',
         '校团委组织社区图书馆志愿服务，欢迎同学报名参加。'),
        ('教师教学发展与培训安排', 'teacher',
         '本学期教师教学培训安排已发布，请各位老师按时参加。'),
    )
    for title, audience, body in fixtures:
        note = Announcement.objects.filter(title=title).first()
        if note is None:
            note = forum_services.create_announcement(
                admin, title, body, audience)
            forum_services.publish_announcement(note, admin)
    return {'announcements': Announcement.objects.count()}


def seed_bookings(rooms):
    from datetime import timedelta

    from django.utils import timezone

    from r21_account.models import Account
    from smass_facilities import services as facility_services
    from smass_facilities.models import RoomBooking

    student = Account.objects.get(login_name='dev_student')
    teacher = Account.objects.get(login_name='dev_teacher')
    base = timezone.now() + timedelta(days=2)
    base = base.replace(hour=14, minute=0, second=0, microsecond=0)
    if not RoomBooking.objects.exists():
        try:
            facility_services.create_booking(
                student, rooms['A102'], base, base + timedelta(hours=2),
                '课程小组讨论', attendees=6)
        except Exception:  # noqa: BLE001
            pass
        try:
            facility_services.create_booking(
                teacher, rooms['A101'], base + timedelta(days=1),
                base + timedelta(days=1, hours=2), '补课', attendees=30)
        except Exception:  # noqa: BLE001
            pass
    return {'bookings': RoomBooking.objects.count()}


def seed_transfer():
    from smass_enrollment import services as enrollment_services
    from smass_enrollment.models import MajorTransferRequest
    from smass_organization.models import OrganizationUnit, StudentRecord

    if MajorTransferRequest.objects.exists():
        return {'transfers': MajorTransferRequest.objects.count()}
    record = StudentRecord.objects.get(student_no='20240103')
    target = OrganizationUnit.objects.get(code='DEV-MAJ-CS')
    enrollment_services.submit_transfer(
        record, target, '对计算机系统方向更感兴趣，已与家长沟通。',
        record.account)
    return {'transfers': MajorTransferRequest.objects.count()}


def seed_workflow():
    from smass_workflow import services as workflow_services
    from smass_workflow.models import Notification, WorkflowDefinition

    if not WorkflowDefinition.objects.filter(code='LEAVE-APPROVAL').exists():
        definition = workflow_services.create_definition(
            'LEAVE-APPROVAL', '学生请假审批流程')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '学生提交', 'start', order=0)
        workflow_services.add_node(version, 'teacher', '辅导员审批', 'approval', order=1)
        workflow_services.add_node(version, 'end', '完成', 'end', order=2)
        workflow_services.add_transition(version, 'start', 'teacher', 'submit')
        workflow_services.add_transition(version, 'teacher', 'end', 'approve')
        workflow_services.publish_version(version)

    workflow_services.notify(
        'dev_student', '课表已发布',
        body='2025-2026 学年第一学期课表已发布，请查看学生工作台。',
        level='info', event_key='seed-timetable-published')
    workflow_services.notify(
        'dev_teacher', '你有新的请假申请',
        body='学生陈晨提交了病假申请，请及时审批。',
        level='warning', event_key='seed-leave-pending')
    return {'notifications': Notification.objects.count()}


def main():
    parser = argparse.ArgumentParser(description='SMASS 产品隔离环境初始化')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--keep-db', action='store_true')
    args = parser.parse_args()

    if not DB_NAME.startswith('smass_product_dev'):
        raise SystemExit('拒绝操作非白名单库：{!r}'.format(DB_NAME))

    cfg = db_config()
    ensure_database(cfg, recreate=not args.keep_db)
    migrate()

    report = {'db': DB_NAME, 'migrate': True}
    report['accounts'] = seed_accounts()
    report['organization'] = seed_organization()
    report['academic'] = seed_academic()
    rooms = seed_facilities()
    report['scheduling'] = {'run': seed_scheduling(rooms).pk}
    report['attendance'] = seed_attendance()
    report['activities'] = seed_activities()
    report['clubs'] = seed_clubs()
    report['finance'] = seed_finance()
    report['bookings'] = seed_bookings(rooms)
    report['transfer'] = seed_transfer()
    report['forum'] = seed_forum_and_notices()
    report['workflow'] = seed_workflow()
    report['password'] = demo_password()
    report['ok'] = True

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
