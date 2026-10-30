"""S10 页面层：再认证 → 发起工单 → 双人批准 → 执行。

运行::

    python manage.py test smass_stepup.tests.test_s10_ui --settings=smass.settings_s10
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_stepup.models import DualApproval, OperationLog

PASSWORD = 'S10Ui#2026'
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


class StepUpUiTests(TestCase):
    def setUp(self):
        self.admin_a = make_account('s10ui-a', [RoleCode.SYSTEM_ADMIN],
                                    person_type='admin')
        self.admin_b = make_account('s10ui-b', [RoleCode.SYSTEM_ADMIN],
                                    person_type='admin')
        self.student = make_account('s10ui-s', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s10/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_open_without_stepup_redirects_to_verify(self):
        login(self.client, 's10ui-a')
        response = self.client.post('/s10/approvals/new/', {
            'action_code': 'reset_other_password',
            'target': 'S001', 'reason': '测试',
        })
        self.assertEqual(302, response.status_code)
        self.assertIn('/s10/verify/', response['Location'])
        self.assertEqual(DualApproval.objects.count(), 0)

    def test_verify_then_open(self):
        login(self.client, 's10ui-a')
        response = self.client.post('/s10/verify/submit/', {
            'action_code': 'reset_other_password',
            'method': 'password', 'code': PASSWORD,
            'next': '/s10/approvals/',
        })
        self.assertEqual(302, response.status_code)
        self.assertIn('ok=', response['Location'])

        response = self.client.post('/s10/approvals/new/', {
            'action_code': 'reset_other_password',
            'target': 'S001', 'reason': '页面测试',
        })
        self.assertEqual(302, response.status_code)
        self.assertEqual(DualApproval.objects.count(), 1)

    def test_wrong_password_keeps_unverified(self):
        login(self.client, 's10ui-a')
        response = self.client.post('/s10/verify/submit/', {
            'action_code': 'reset_other_password',
            'method': 'password', 'code': 'wrong',
        })
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])

    def test_full_two_person_flow_via_pages(self):
        # 发起人再认证 + 发起
        login(self.client, 's10ui-a')
        self.client.post('/s10/verify/submit/', {
            'action_code': 'reset_other_password',
            'method': 'password', 'code': PASSWORD,
        })
        self.client.post('/s10/approvals/new/', {
            'action_code': 'reset_other_password',
            'target': 'S001', 'reason': '页面全流程',
        })
        approval = DualApproval.objects.get()

        # 另一个管理员批准
        approver = Client()
        login(approver, 's10ui-b')
        response = approver.post(
            '/s10/approvals/{}/approve/'.format(approval.pk))
        self.assertEqual(302, response.status_code)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'approved')

        # 发起人执行
        response = self.client.post(
            '/s10/approvals/{}/execute/'.format(approval.pk))
        self.assertEqual(302, response.status_code)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'executed')
        self.assertEqual(OperationLog.objects.filter(
            approval_id=approval.pk).count(), 1)

    def test_student_cannot_approve_via_page(self):
        login(self.client, 's10ui-a')
        self.client.post('/s10/verify/submit/', {
            'action_code': 'reset_other_password',
            'method': 'password', 'code': PASSWORD,
        })
        self.client.post('/s10/approvals/new/', {
            'action_code': 'reset_other_password',
            'target': 'S001', 'reason': '测试',
        })
        approval = DualApproval.objects.get()

        student = Client()
        login(student, 's10ui-s')
        response = student.post('/s10/approvals/{}/approve/'.format(approval.pk))
        self.assertEqual(403, response.status_code)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'pending')

    def test_student_sees_only_own_approvals(self):
        login(self.client, 's10ui-a')
        self.client.post('/s10/verify/submit/', {
            'action_code': 'reset_other_password',
            'method': 'password', 'code': PASSWORD,
        })
        self.client.post('/s10/approvals/new/', {
            'action_code': 'reset_other_password',
            'target': 'SECRET-TARGET', 'reason': '不该给别人看',
        })

        student = Client()
        login(student, 's10ui-s')
        response = student.get('/s10/approvals/')
        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, 'SECRET-TARGET')
