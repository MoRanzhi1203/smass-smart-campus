"""S11 页面层：策略配置与预览。

运行::

    python manage.py test smass_policy.tests.test_s11_ui --settings=smass.settings_s11
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_policy.models import FieldPolicy

PASSWORD = 'S11Ui#2026'
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


class PolicyUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.record = StudentRecord.objects.create(
            student_no='S11UI01', name='李四', unit=self.klass,
            extra={'phone': '13800001234'})

        self.admin = make_account('s11uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s11uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s11/preview/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_policies(self):
        login(self.client, 's11uistu')
        self.assertEqual(403, self.client.get('/s11/policies/').status_code)

    def test_admin_saves_policy_via_page(self):
        admin = Client()
        login(admin, 's11uiadmin')
        response = admin.post('/s11/policies/save/', {
            'resource': 'student_record', 'field': 'phone',
            'read_roles': 'student', 'write_roles': '',
            'mask': 'partial', 'condition_status': 'enrolled',
            'note': '界面策略',
        })
        self.assertEqual(302, response.status_code)
        policy = FieldPolicy.objects.get(resource='student_record', field='phone')
        self.assertEqual(policy.mask, 'partial')
        self.assertEqual(policy.condition, {'status': ['enrolled']})

    def test_student_preview_masks_phone(self):
        auth = Client()
        login(auth, 's11uiadmin')
        auth.post('/s11/policies/save/', {
            'resource': 'student_record', 'field': 'phone',
            'read_roles': 'student', 'mask': 'partial',
        })

        login(self.client, 's11uistu')
        response = self.client.get('/s11/preview/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '已脱敏')
        self.assertContains(response, '138****34')
        self.assertNotContains(response, '13800001234')

    def test_preview_denied_without_policy(self):
        login(self.client, 's11uistu')
        response = self.client.get('/s11/preview/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '尚未配置任何字段策略')

    def test_disable_policy_via_page(self):
        auth = Client()
        login(auth, 's11uiadmin')
        auth.post('/s11/policies/save/', {
            'resource': 'student_record', 'field': 'phone',
            'read_roles': 'student', 'mask': 'none',
        })
        policy = FieldPolicy.objects.get(field='phone')

        response = auth.post('/s11/policies/{}/disable/'.format(policy.pk))
        self.assertEqual(302, response.status_code)
        policy.refresh_from_db()
        self.assertFalse(policy.enabled)

        login(self.client, 's11uistu')
        response = self.client.get('/s11/preview/')
        self.assertContains(response, '尚未配置任何字段策略')

    def test_preview_with_invalid_record_param(self):
        login(self.client, 's11uistu')
        response = self.client.get('/s11/preview/', {'record': "' OR 1=1 --"})
        self.assertEqual(200, response.status_code)
