"""S09 页面层：强制绑定、二次验证与状态页。

运行::

    python manage.py test smass_mfa.tests.test_s09_ui --settings=smass.settings_s09
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_mfa import services
from smass_mfa.models import MfaDevice

PASSWORD = 'S09Ui#2026'
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


class MfaUiTests(TestCase):
    def setUp(self):
        self.admin = make_account('s09uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s09uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s09/setup/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_privileged_forced_to_setup(self):
        login(self.client, 's09uiadmin')
        response = self.client.get('/r21/home/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/s09/setup/', response['Location'])

    def test_student_not_affected(self):
        login(self.client, 's09uistu')
        self.assertEqual(200, self.client.get('/r21/home/').status_code)

    def test_setup_page_shows_secret(self):
        login(self.client, 's09uiadmin')
        response = self.client.get('/s09/setup/')
        self.assertEqual(200, response.status_code)
        device = MfaDevice.objects.get(account=self.admin)
        self.assertContains(response, device.secret)
        self.assertContains(response, 'otpauth://totp/')

    def test_full_flow_setup_then_verify(self):
        login(self.client, 's09uiadmin')
        self.assertEqual(200, self.client.get('/s09/setup/').status_code)
        response = self.client.post('/s09/setup/', {
            'code': services.totp(MfaDevice.objects.get(account=self.admin).secret),
            'next': '/r21/home/',
        })
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '一次性恢复码')

        # 绑定过程本身已验证，当前会话直接放行
        self.assertEqual(200, self.client.get('/r21/home/').status_code)

        # 新会话登录后必须二次验证
        fresh = Client()
        login(fresh, 's09uiadmin')
        response = fresh.get('/r21/home/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/s09/verify/', response['Location'])

        device = MfaDevice.objects.get(account=self.admin)
        response = fresh.post(
            '/s09/verify/',
            {'code': services.totp(device.secret), 'next': '/r21/home/'})
        self.assertEqual(302, response.status_code)
        self.assertEqual('/r21/home/', response['Location'])
        self.assertEqual(200, fresh.get('/r21/home/').status_code)

    def test_wrong_setup_code_redirects_with_error(self):
        login(self.client, 's09uiadmin')
        response = self.client.post('/s09/setup/', {'code': '000000'})
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])

    def test_status_page(self):
        login(self.client, 's09uiadmin')
        response = self.client.get('/s09/status/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '多因素认证状态')

    def test_disable_requires_valid_code(self):
        device, _ = services.enroll(self.admin)
        services.confirm(self.admin, services.totp(device.secret))

        admin = Client()
        login(admin, 's09uiadmin')
        admin.post('/s09/verify/', {'code': services.totp(device.secret)})

        response = admin.post('/s09/disable/', {'code': '000000'})
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])
        device.refresh_from_db()
        self.assertEqual(device.status, 'active')
