"""R13 页面层：考勤会话、签到、请假销假、补签与权限负向。

运行::

    python manage.py test smass_attendance.tests.test_r13_ui --settings=smass.settings_r13
"""
from __future__ import annotations

import datetime as dt

from django.test import Client, TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_attendance.models import (
    AttendanceRecord,
    AttendanceSession,
    LeaveRequest,
    MakeupRequest,
)

PASSWORD = 'R13Ui#2026'
LOGIN = '/r21/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


class AttendanceUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.klass2 = OrganizationUnit.objects.create(
            code='CL02', name='二班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('r13uiteacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('r13uistu', [RoleCode.STUDENT])
        self.outsider = make_account('r13uiout', [RoleCode.STUDENT])

        self.me = StudentRecord.objects.create(
            student_no='S7001', name='界面学生', unit=self.klass, account=self.student)
        StudentRecord.objects.create(
            student_no='S7002', name='外班学生', unit=self.klass2, account=self.outsider)

    def test_requires_login(self):
        response = self.client.get('/r13/sessions/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_stats(self):
        login(self.client, 'r13uistu')
        self.assertEqual(403, self.client.get('/r13/stats/').status_code)

    def test_teacher_creates_session_via_page(self):
        login(self.client, 'r13uiteacher')
        response = self.client.post('/r13/sessions/create/', {
            'unit': self.klass.pk,
            'session_date': timezone.localdate().isoformat(),
            'period': '第1-2节',
            'topic': '界面创建',
        })
        self.assertEqual(302, response.status_code)
        session = AttendanceSession.objects.get(unit=self.klass)
        self.assertEqual(len(session.code), 6)

        detail = self.client.get('/r13/sessions/{}/'.format(session.pk))
        self.assertEqual(200, detail.status_code)
        self.assertContains(detail, session.code)

    def test_student_signs_via_page(self):
        session = AttendanceSession.objects.create(
            unit=self.klass, session_date=timezone.localdate(),
            period='第1-2节', status='open', code='654321',
            code_expires_at=timezone.now() + dt.timedelta(minutes=10))
        login(self.client, 'r13uistu')
        response = self.client.post(
            '/r13/sessions/{}/sign/'.format(session.pk), {'code': '654321'})
        self.assertEqual(302, response.status_code)
        record = AttendanceRecord.objects.get(session=session, record=self.me)
        self.assertEqual(record.status, 'present')

    def test_student_cannot_view_other_class_session(self):
        other_session = AttendanceSession.objects.create(
            unit=self.klass2, session_date=timezone.localdate(),
            period='第3-4节', status='open', code='111111')
        login(self.client, 'r13uistu')
        response = self.client.get('/r13/sessions/{}/'.format(other_session.pk))
        self.assertEqual(403, response.status_code)

    def test_student_submits_leave_and_teacher_approves(self):
        login(self.client, 'r13uistu')
        response = self.client.post('/r13/leaves/submit/', {
            'leave_type': 'personal',
            'start_date': timezone.localdate().isoformat(),
            'end_date': (timezone.localdate() + dt.timedelta(days=1)).isoformat(),
            'reason': '界面请假',
        })
        self.assertEqual(302, response.status_code)
        leave = LeaveRequest.objects.get(record=self.me)
        self.assertEqual(leave.status, 'submitted')

        teacher = Client()
        login(teacher, 'r13uiteacher')
        response = teacher.post('/r13/leaves/{}/approve/'.format(leave.pk))
        self.assertEqual(302, response.status_code)
        leave.refresh_from_db()
        self.assertEqual(leave.status, 'approved')

    def test_student_cannot_approve_leave(self):
        leave = LeaveRequest.objects.create(
            record=self.me, leave_type='personal',
            start_date=timezone.localdate(),
            end_date=timezone.localdate(), reason='待审批', status='submitted')
        login(self.client, 'r13uistu')
        response = self.client.post('/r13/leaves/{}/approve/'.format(leave.pk))
        self.assertEqual(403, response.status_code)

    def test_makeup_flow_via_page(self):
        session = AttendanceSession.objects.create(
            unit=self.klass, session_date=timezone.localdate(),
            period='第1-2节', status='closed', code='')
        AttendanceRecord.objects.create(
            session=session, record=self.me, status='absent', source='teacher')

        login(self.client, 'r13uistu')
        response = self.client.post('/r13/makeups/submit/', {
            'session': session.pk,
            'reason': '界面补签',
        })
        self.assertEqual(302, response.status_code)
        makeup = MakeupRequest.objects.get(record=self.me)
        self.assertEqual(makeup.status, 'submitted')

        teacher = Client()
        login(teacher, 'r13uiteacher')
        response = teacher.post('/r13/makeups/{}/approve/'.format(makeup.pk))
        self.assertEqual(302, response.status_code)
        self.assertEqual(AttendanceRecord.objects.get(
            session=session, record=self.me).status, 'present')

    def test_teacher_closes_session_via_page(self):
        session = AttendanceSession.objects.create(
            unit=self.klass, session_date=timezone.localdate(),
            period='第1-2节', status='open', code='222222',
            code_expires_at=timezone.now() + dt.timedelta(minutes=10))
        login(self.client, 'r13uiteacher')
        response = self.client.post('/r13/sessions/{}/close/'.format(session.pk))
        self.assertEqual(302, response.status_code)
        session.refresh_from_db()
        self.assertEqual(session.status, 'closed')
        self.assertEqual(AttendanceRecord.objects.get(
            session=session, record=self.me).status, 'absent')
