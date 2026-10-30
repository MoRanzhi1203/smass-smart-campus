"""S13 页面层：字段分级、披露申请、执行与下载。

运行::

    python manage.py test smass_privacy.tests.test_s13_ui --settings=smass.settings_s13
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

from smass_privacy.models import DataField, DisclosureRequest

PASSWORD = 'S13Ui#2026'
LOGIN = '/r21/login/'
PHONE = '13800001234'


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


class PrivacyUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        StudentRecord.objects.create(
            student_no='S13UI01', name='钱七', unit=self.klass,
            extra={'phone': PHONE})

        self.admin = make_account('s13uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s13uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s13/disclosures/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_fields(self):
        login(self.client, 's13uistu')
        self.assertEqual(403, self.client.get('/s13/fields/').status_code)

    def test_admin_configures_field(self):
        admin = Client()
        login(admin, 's13uiadmin')
        response = admin.post('/s13/fields/save/', {
            'resource': 'student_record', 'field': 'phone',
            'classification': 'personal', 'mask': 'none',
            'retention_days': '0',
        })
        self.assertEqual(302, response.status_code)
        policy = DataField.objects.get(resource='student_record', field='phone')
        self.assertEqual(policy.classification, 'personal')

    def test_full_flow_with_masked_export(self):
        auth = Client()
        login(auth, 's13uiadmin')
        auth.post('/s13/fields/save/', {
            'resource': 'student_record', 'field': 'phone',
            'classification': 'personal', 'mask': 'none',
        })

        login(self.client, 's13uistu')
        response = self.client.post('/s13/disclosures/new/', {
            'fields': ['phone'], 'purpose': '界面披露',
        })
        self.assertEqual(302, response.status_code)
        request_row = DisclosureRequest.objects.get()

        response = auth.post(
            '/s13/disclosures/{}/approve/'.format(request_row.pk))
        self.assertEqual(302, response.status_code)
        request_row.refresh_from_db()
        self.assertEqual(request_row.status, 'approved')

        response = self.client.post(
            '/s13/disclosures/{}/execute/'.format(request_row.pk))
        self.assertEqual(302, response.status_code)
        request_row.refresh_from_db()
        self.assertEqual(request_row.status, 'executed')

        response = self.client.get(
            '/s13/disclosures/{}/export/'.format(request_row.pk))
        self.assertEqual(200, response.status_code)
        content = response.content.decode('utf-8')
        self.assertIn('138****34', content)
        self.assertNotIn(PHONE, content)

    def test_student_cannot_approve(self):
        auth = Client()
        login(auth, 's13uiadmin')
        auth.post('/s13/fields/save/', {
            'resource': 'student_record', 'field': 'phone',
            'classification': 'personal', 'mask': 'none',
        })
        login(self.client, 's13uistu')
        self.client.post('/s13/disclosures/new/', {
            'fields': ['phone'], 'purpose': '界面披露',
        })
        request_row = DisclosureRequest.objects.get()

        response = self.client.post(
            '/s13/disclosures/{}/approve/'.format(request_row.pk))
        self.assertEqual(403, response.status_code)
        request_row.refresh_from_db()
        self.assertEqual(request_row.status, 'pending')

    def test_export_requires_executed(self):
        auth = Client()
        login(auth, 's13uiadmin')
        auth.post('/s13/fields/save/', {
            'resource': 'student_record', 'field': 'phone',
            'classification': 'personal', 'mask': 'none',
        })
        login(self.client, 's13uistu')
        self.client.post('/s13/disclosures/new/', {
            'fields': ['phone'], 'purpose': '界面披露',
        })
        request_row = DisclosureRequest.objects.get()
        response = self.client.get(
            '/s13/disclosures/{}/export/'.format(request_row.pk))
        self.assertEqual(403, response.status_code)
