"""R19 页面层：组织、成员、活动、受控资料与借阅审批的真实页面流程。

运行::

    python manage.py test smass_party.tests.test_r19_ui --settings=smass.settings_r19
"""
from __future__ import annotations

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

from smass_party.models import AccessLog, AccessRequest, PartyDocument, PartyOrg

PASSWORD = 'R19Ui#2026'
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


class PartyUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('r19uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r19uistu', [RoleCode.STUDENT])
        self.outsider = make_account('r19uiout', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9501', name='成员学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S9502', name='外组织学生', unit=self.klass, account=self.outsider)

        self.org = PartyOrg.objects.create(
            code='BR-UI', name='界面党支部', org_type='branch', status='active')
        self.sensitive = PartyDocument.objects.create(
            org=self.org, title='界面敏感资料', classification='sensitive',
            summary='合成摘要内容', status='published')
        self.internal = PartyDocument.objects.create(
            org=self.org, title='界面内部纪要', classification='internal',
            summary='内部摘要', status='published')

    def test_requires_login(self):
        response = self.client.get('/r19/orgs/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_audit(self):
        login(self.client, 'r19uistu')
        self.assertEqual(403, self.client.get('/r19/audit/').status_code)

    def test_admin_creates_org_and_document(self):
        admin = Client()
        login(admin, 'r19uiadmin')
        response = admin.post('/r19/orgs/create/', {
            'code': 'BR-NEW', 'name': '新建党支部', 'org_type': 'branch',
        })
        self.assertEqual(302, response.status_code)
        org = PartyOrg.objects.get(code='BR-NEW')

        response = admin.post('/r19/orgs/{}/documents/add/'.format(org.pk), {
            'title': '新建资料', 'classification': 'sensitive', 'summary': '合成摘要',
        })
        self.assertEqual(302, response.status_code)
        self.assertTrue(PartyDocument.objects.filter(title='新建资料').exists())

    def test_sensitive_document_masked_and_request(self):
        login(self.client, 'r19uistu')
        response = self.client.get('/r19/documents/{}/'.format(self.sensitive.pk))
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '受控资料')
        self.assertNotContains(response, '合成摘要内容')

        self.assertEqual(AccessLog.objects.filter(
            document=self.sensitive, action='deny').count(), 1)

        response = self.client.post('/r19/documents/{}/request/'.format(
            self.sensitive.pk), {'purpose': '页面申请'})
        self.assertEqual(302, response.status_code)
        self.assertEqual(AccessRequest.objects.filter(
            document=self.sensitive).count(), 1)

    def test_admin_approves_and_student_can_view(self):
        request = AccessRequest.objects.create(
            document=self.sensitive, applicant=self.student,
            purpose='页面申请', status='submitted')

        admin = Client()
        login(admin, 'r19uiadmin')
        response = admin.post('/r19/access/{}/approve/'.format(request.pk))
        self.assertEqual(302, response.status_code)
        request.refresh_from_db()
        self.assertEqual(request.status, 'approved')

        login(self.client, 'r19uistu')
        response = self.client.get('/r19/documents/{}/'.format(self.sensitive.pk))
        self.assertContains(response, '合成摘要内容')
        self.assertEqual(AccessLog.objects.filter(
            document=self.sensitive, action='view').count(), 1)

    def test_internal_requires_membership(self):
        login(self.client, 'r19uiout')
        response = self.client.get('/r19/documents/{}/'.format(self.internal.pk))
        self.assertContains(response, '受控资料')
        self.assertNotContains(response, '内部摘要')

    def test_student_cannot_create_org(self):
        login(self.client, 'r19uistu')
        response = self.client.post('/r19/orgs/create/', {
            'code': 'BR-X', 'name': '非法', 'org_type': 'branch',
        })
        self.assertEqual(403, response.status_code)
