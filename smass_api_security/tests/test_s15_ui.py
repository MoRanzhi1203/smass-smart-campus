"""S15 页面层：API 客户端/令牌管理与请求日志。

运行::

    python manage.py test smass_api_security.tests.test_s15_ui --settings=smass.settings_s15 --noinput
"""
from __future__ import annotations

import time

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_api_security.models import ApiClient, ApiToken

PASSWORD = 'S15Ui#2026'
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


class ApiUiTests(TestCase):
    def setUp(self):
        self.admin = make_account('s15uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s15uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s15/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden(self):
        login(self.client, 's15uistu')
        self.assertEqual(403, self.client.get('/s15/').status_code)

    def test_admin_creates_client_and_token(self):
        admin = Client()
        login(admin, 's15uiadmin')
        response = admin.post('/s15/clients/new/', {'name': '界面客户端'})
        self.assertEqual(302, response.status_code)
        client_obj = ApiClient.objects.get(name='界面客户端')

        response = admin.post('/s15/tokens/new/', {
            'client': client_obj.pk, 'scopes': 'students:read', 'ttl': '600',
        })
        self.assertEqual(302, response.status_code)
        token = ApiToken.objects.get(client=client_obj)
        self.assertEqual(token.scopes, 'students:read')

        # 令牌明文只在重定向后的页面展示一次
        page = admin.get('/s15/')
        self.assertContains(page, '新令牌（仅显示一次）')
        self.assertContains(page, token.token_hash[:10])

        again = admin.get('/s15/')
        self.assertNotContains(again, '新令牌（仅显示一次）')

    def test_admin_revokes_token(self):
        admin = Client()
        login(admin, 's15uiadmin')
        admin.post('/s15/clients/new/', {'name': '待吊销'})
        client_obj = ApiClient.objects.get(name='待吊销')
        admin.post('/s15/tokens/new/', {
            'client': client_obj.pk, 'scopes': 'students:read', 'ttl': '600',
        })
        token = ApiToken.objects.get(client=client_obj)

        response = admin.post('/s15/tokens/{}/revoke/'.format(token.pk))
        self.assertEqual(302, response.status_code)
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)

    def test_request_log_visible(self):
        admin = Client()
        login(admin, 's15uiadmin')
        admin.post('/s15/clients/new/', {'name': '日志客户端'})
        client_obj = ApiClient.objects.get(name='日志客户端')
        admin.post('/s15/tokens/new/', {
            'client': client_obj.pk, 'scopes': '', 'ttl': '600',
        })
        page = admin.get('/s15/')
        raw = page.context['issued_token'] if page.context else ''
        self.assertTrue(raw)

        headers = {
            'HTTP_AUTHORIZATION': 'Bearer {}'.format(raw),
            'HTTP_X_TIMESTAMP': str(int(time.time())),
            'HTTP_X_NONCE': 'ui-nonce-1',
        }
        self.client.get('/s15/api/v1/ping', **headers)
        page = admin.get('/s15/')
        self.assertContains(page, '/s15/api/v1/ping')
