"""R11-UI 验收：排课规划页与三张课表的可见流程。

覆盖：
- 未登录跳转、学生不能进规划页（403）；
- 求解 → 发布 的完整链路（发布前独立复核）；
- 学生课表按 Enrollment 收窄、教师课表按本人收窄、教室课表限管理员；
- 只有 `published` 批次对课表可见；
- 我的课表 JSON。

运行::

    python manage.py test smass_scheduling.tests.test_r11_ui --settings=smass.settings_r11
"""
from __future__ import annotations

import datetime as dt
import json

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_academic.models import (
    AcademicTerm,
    AcademicYear,
    Course,
    Enrollment,
    TeachingSection,
)
from smass_facilities.models import Building, Room
from smass_scheduling import solver
from smass_scheduling.models import (
    RUN_PUBLISHED,
    RUN_SOLVED,
    Cohort,
    LessonRequirement,
    ScheduleRun,
    TimeSlot,
)

PASSWORD = 'R11Ui#2024'


def make_account(login_name, roles, person_type='teacher'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post('/r11/login/', {'login_name': login_name,
                                       'password': PASSWORD})


def build_world():
    """构造一个最小可排课世界并求解（不发布）。"""
    for weekday in range(3):
        for period in range(1, 4):
            TimeSlot.objects.get_or_create(
                weekday=weekday, period=period,
                defaults={'start_time': dt.time(8 + period - 1, 0),
                          'end_time': dt.time(9 + period - 1, 0)})

    year, _ = AcademicYear.objects.get_or_create(
        code='2024-2025',
        defaults={'start_date': dt.date(2024, 9, 2),
                  'end_date': dt.date(2025, 1, 17)})
    term, _ = AcademicTerm.objects.get_or_create(
        year=year, semester='1',
        defaults={'name': '2024 秋', 'start_date': dt.date(2024, 9, 2),
                  'end_date': dt.date(2025, 1, 17)})

    building, _ = Building.objects.get_or_create(code='B1', defaults={'name': '主楼'})
    room, _ = Room.objects.get_or_create(
        code='R101',
        defaults={'name': 'R101', 'building': building, 'capacity': 50})

    course, _ = Course.objects.get_or_create(
        code='CS101', defaults={'title': '程序设计基础', 'credit': 3})
    section, _ = TeachingSection.objects.get_or_create(
        term=term, course=course, code='CS101-01', defaults={'capacity': 50})

    admin = make_account('R11ADM', [RoleCode.SYSTEM_ADMIN], person_type='admin')
    teacher = make_account('R11T', [RoleCode.TEACHER])
    student = make_account('R11S', [RoleCode.STUDENT], person_type='student')

    Enrollment.objects.get_or_create(section=section, account=student,
                                     defaults={'status': 'enrolled'})

    cohort, _ = Cohort.objects.get_or_create(code='C1', defaults={'name': '软工2101',
                                                                 'size': 40})
    run = ScheduleRun.objects.create(term=term, created_by='R11ADM')
    LessonRequirement.objects.create(
        run=run, section=section, teacher=teacher, cohort=cohort,
        weekly_sessions=1, session_periods=2, students=40)

    solver.solve(run)
    run.refresh_from_db()
    return {'term': term, 'room': room, 'section': section, 'run': run,
            'admin': admin, 'teacher': teacher, 'student': student}


class PlanPageTests(TestCase):
    def setUp(self):
        self.world = build_world()

    def test_anonymous_redirected(self):
        resp = Client().get('/r11/plan/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/r11/login/', resp['Location'])

    def test_student_forbidden(self):
        client = Client()
        login(client, 'R11S')
        resp = client.get('/r11/plan/')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_open_plan(self):
        client = Client()
        login(client, 'R11ADM')
        resp = client.get('/r11/plan/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '排课规划')
        self.assertContains(resp, '程序')

    def test_teacher_forbidden_on_plan(self):
        client = Client()
        login(client, 'R11T')
        resp = client.get('/r11/plan/')
        self.assertEqual(resp.status_code, 403)


class SolveAndPublishTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.run = self.world['run']

    def test_solve_endpoint_returns_result(self):
        client = Client()
        login(client, 'R11ADM')
        resp = client.post('/r11/plan/{}/solve/'.format(self.run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['feasible'], data.get('explanation'))
        self.assertEqual(data['hard_conflicts'], 0)

    def test_solve_requires_permission(self):
        client = Client()
        login(client, 'R11T')
        resp = client.post('/r11/plan/{}/solve/'.format(self.run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_publish_requires_solved(self):
        run = ScheduleRun.objects.create(term=self.world['term'])
        client = Client()
        login(client, 'R11ADM')
        resp = client.post('/r11/plan/{}/publish/'.format(run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('已求解', resp.json()['error'])

    def test_publish_after_solve(self):
        client = Client()
        login(client, 'R11ADM')
        resp = client.post('/r11/plan/{}/publish/'.format(self.run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, RUN_PUBLISHED)
        self.assertIsNotNone(self.run.published_at)

    def test_publish_rejected_when_verify_fails(self):
        """发布前独立复核：人为把课时需求改大导致节次不符。"""
        req = self.run.requirements.first()
        req.weekly_sessions = 5
        req.save(update_fields=['weekly_sessions'])
        client = Client()
        login(client, 'R11ADM')
        resp = client.post('/r11/plan/{}/publish/'.format(self.run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('复核', resp.json()['error'])

    def test_conflicts_endpoint(self):
        client = Client()
        login(client, 'R11ADM')
        resp = client.get('/r11/plan/{}/conflicts/'.format(self.run.pk),
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['conflicts'], [])

    def test_published_run_cannot_be_resolved(self):
        self.run.status = RUN_PUBLISHED
        self.run.save(update_fields=['status'])
        client = Client()
        login(client, 'R11ADM')
        resp = client.post('/r11/plan/{}/solve/'.format(self.run.pk),
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)


class TimetableVisibilityTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.run = self.world['run']

    def _publish(self):
        self.run.status = RUN_PUBLISHED
        from django.utils import timezone
        self.run.published_at = timezone.now()
        self.run.save(update_fields=['status', 'published_at'])

    def test_student_timetable_empty_before_publish(self):
        client = Client()
        login(client, 'R11S')
        resp = client.get('/r11/timetable/student/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '还没有已发布的排课批次')

    def test_student_timetable_after_publish(self):
        self._publish()
        client = Client()
        login(client, 'R11S')
        resp = client.get('/r11/timetable/student/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '程序设计基础')
        self.assertContains(resp, 'CS101-01')

    def test_teacher_timetable_after_publish(self):
        self._publish()
        client = Client()
        login(client, 'R11T')
        resp = client.get('/r11/timetable/teacher/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '程序设计基础')

    def test_other_teacher_sees_nothing(self):
        self._publish()
        other = make_account('R11T2', [RoleCode.TEACHER])
        client = Client()
        login(client, 'R11T2')
        resp = client.get('/r11/timetable/teacher/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '没有与你相关的课次')

    def test_room_timetable_admin_only(self):
        self._publish()
        room = self.world['room']

        teacher_client = Client()
        login(teacher_client, 'R11T')
        self.assertEqual(
            teacher_client.get('/r11/timetable/room/{}/'.format(room.pk)).status_code, 403)

        admin_client = Client()
        login(admin_client, 'R11ADM')
        resp = admin_client.get('/r11/timetable/room/{}/'.format(room.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '教室课表')

    def test_my_timetable_json(self):
        self._publish()
        client = Client()
        login(client, 'R11S')
        resp = client.get('/r11/timetable/mine.json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['run'], self.run.pk)
        self.assertTrue(data['entries'])
        first = data['entries'][0]
        for key in ('weekday', 'period', 'course', 'section', 'teacher', 'room', 'cohort'):
            self.assertIn(key, first)

    def test_anonymous_timetable_redirected(self):
        resp = Client().get('/r11/timetable/student/')
        self.assertEqual(resp.status_code, 302)
