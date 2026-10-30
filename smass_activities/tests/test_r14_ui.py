"""R14 页面层：活动、报名签到、学分认定的真实页面流程与权限负向。

运行::

    python manage.py test smass_activities.tests.test_r14_ui --settings=smass.settings_r14
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

from smass_activities.models import Activity, ActivityCredit, ActivityRegistration

PASSWORD = 'R14Ui#2026'
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


def fmt(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


class ActivityUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('r14uiteacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.admin = make_account('r14uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r14uistu', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S7201', name='界面学生', unit=self.klass, account=self.student)

        now = timezone.now()
        self.activity = Activity.objects.create(
            title='界面活动', category='volunteer', location='礼堂',
            start_at=now + dt.timedelta(hours=1),
            end_at=now + dt.timedelta(hours=3),
            capacity=2, credit_points=1, volunteer_hours=2,
            status='published', checkin_code='123456',
            created_by=str(self.teacher.pk))

    def test_requires_login(self):
        response = self.client.get('/r14/activities/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_cannot_create_activity(self):
        login(self.client, 'r14uistu')
        response = self.client.post('/r14/activities/create/', {
            'title': '非法', 'category': 'club',
            'start_at': fmt(timezone.now() + dt.timedelta(hours=1)),
            'end_at': fmt(timezone.now() + dt.timedelta(hours=2)),
        })
        self.assertEqual(403, response.status_code)

    def test_teacher_creates_and_publishes(self):
        teacher = Client()
        login(teacher, 'r14uiteacher')
        response = teacher.post('/r14/activities/create/', {
            'title': '教师创建', 'category': 'lecture',
            'start_at': fmt(timezone.now() + dt.timedelta(hours=1)),
            'end_at': fmt(timezone.now() + dt.timedelta(hours=2)),
            'capacity': '10', 'credit_points': '0.5',
        })
        self.assertEqual(302, response.status_code)
        activity = Activity.objects.get(title='教师创建')
        self.assertEqual(activity.status, 'draft')

        response = teacher.post('/r14/activities/{}/publish/'.format(activity.pk))
        self.assertEqual(302, response.status_code)
        activity.refresh_from_db()
        self.assertEqual(activity.status, 'published')

    def test_student_registers_via_page(self):
        login(self.client, 'r14uistu')
        response = self.client.post('/r14/activities/{}/register/'.format(
            self.activity.pk))
        self.assertEqual(302, response.status_code)
        self.assertEqual(ActivityRegistration.objects.get(
            activity=self.activity, record=self.me).status, 'registered')

    def test_student_checks_in_via_page(self):
        Activity.objects.filter(pk=self.activity.pk).update(
            start_at=timezone.now() - dt.timedelta(minutes=10),
            end_at=timezone.now() + dt.timedelta(hours=1))
        self.activity.refresh_from_db()
        registration = ActivityRegistration.objects.create(
            activity=self.activity, record=self.me, status='registered')

        login(self.client, 'r14uistu')
        response = self.client.post('/r14/registrations/{}/checkin/'.format(
            registration.pk), {'code': '123456'})
        self.assertEqual(302, response.status_code)
        registration.refresh_from_db()
        self.assertEqual(registration.status, 'checked_in')

    def test_student_cancels_registration(self):
        login(self.client, 'r14uistu')
        self.client.post('/r14/activities/{}/register/'.format(self.activity.pk))
        registration = ActivityRegistration.objects.get(
            activity=self.activity, record=self.me)
        response = self.client.post('/r14/registrations/{}/cancel/'.format(
            registration.pk))
        self.assertEqual(302, response.status_code)
        registration.refresh_from_db()
        self.assertEqual(registration.status, 'cancelled')

    def test_credit_approval_via_page(self):
        registration = ActivityRegistration.objects.create(
            activity=self.activity, record=self.me, status='checked_in')
        Activity.objects.filter(pk=self.activity.pk).update(status='closed')
        self.activity.refresh_from_db()
        from smass_activities import services as activity_services
        activity_services.generate_credits(self.activity, self.teacher)
        credit = ActivityCredit.objects.get(activity=self.activity)

        admin = Client()
        login(admin, 'r14uiadmin')
        response = admin.post('/r14/credits/{}/approve/'.format(credit.pk))
        self.assertEqual(302, response.status_code)
        credit.refresh_from_db()
        self.assertEqual(credit.status, 'approved')

    def test_student_cannot_approve_credit(self):
        ActivityRegistration.objects.create(
            activity=self.activity, record=self.me, status='checked_in')
        Activity.objects.filter(pk=self.activity.pk).update(status='closed')
        self.activity.refresh_from_db()
        from smass_activities import services as activity_services
        activity_services.generate_credits(self.activity, self.teacher)
        credit = ActivityCredit.objects.get(activity=self.activity)

        login(self.client, 'r14uistu')
        response = self.client.post('/r14/credits/{}/approve/'.format(credit.pk))
        self.assertEqual(403, response.status_code)
