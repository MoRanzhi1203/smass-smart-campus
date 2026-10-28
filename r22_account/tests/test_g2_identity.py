"""G2：``request.account`` 契约与请求缓存。"""
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from r21_account.models import Account
from r22_account import identity as identity_module
from r22_account.tests import helpers


class AccountContractTests(TestCase):
    def test_anonymous_has_no_account(self):
        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(status, 200)
        self.assertEqual(payload['kind'], 'anonymous')
        self.assertFalse(payload['has_account'])
        self.assertIsNone(payload['account_login'])

    def test_valid_account_is_account_instance(self):
        account = helpers.make_account('T200001')
        helpers.login_account(self.client, 'T200001')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'account')
        self.assertTrue(payload['has_account'])
        self.assertEqual(payload['account_login'], 'T200001')
        self.assertEqual(payload['account_type'], 'Account')

    def test_request_user_is_not_monkeypatched(self):
        """``request.user`` 仍是 Django 解析出的 Account；``request.account`` 指向同一账号。"""
        helpers.make_account('T200002')
        helpers.login_account(self.client, 'T200002')

        resp = self.client.get('/identity/')
        request = resp.wsgi_request
        self.assertIsInstance(request.user, Account)
        self.assertIsInstance(request.account, Account)
        self.assertEqual(request.account.pk, request.user.pk)

    def test_account_is_plain_instance_not_lazy(self):
        """契约：``request.account`` 语义上必须是 ``Account``（或 None），不能是 auth.User。

        实现上用 Django 标准的 ``SimpleLazyObject`` 代理（保持懒解析），
        因此断言用 ``isinstance`` 而不是 ``type().__name__``。
        """
        helpers.make_account('T200006')
        helpers.login_account(self.client, 'T200006')

        resp = self.client.get('/identity/')
        account = resp.wsgi_request.account
        self.assertIsInstance(account, Account)
        self.assertNotEqual(type(account).__name__, 'User')
        self.assertEqual(account.login_name, 'T200006')

    def test_disabled_account_is_denied(self):
        account = helpers.make_account('T200003')
        helpers.login_account(self.client, 'T200003')

        account.is_active = False
        account.save(update_fields=['is_active'])

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'anonymous')
        self.assertFalse(payload['has_account'])

    def test_legacy_only_yields_legacy_identity(self):
        helpers.set_legacy_session(self.client, 'teacher', 'T300001')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'legacy')
        self.assertFalse(payload['has_account'])
        self.assertEqual(payload['legacy_role'], 'teacher')
        self.assertEqual(payload['legacy_id'], 'T300001')

    def test_invalid_legacy_role_is_ignored(self):
        helpers.set_legacy_session(self.client, 'superuser', 'X')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'anonymous')

    def test_spoofed_query_params_do_not_change_identity(self):
        helpers.set_legacy_session(self.client, 'student', 'S1')

        resp = self.client.get(
            '/identity/?account=admin&account_id=1&role=admin&kind=dual'
        )
        payload = resp.json()['identity']
        self.assertEqual(payload['kind'], 'legacy')
        self.assertFalse(payload['has_account'])

    def test_identity_resolved_once_per_request(self):
        helpers.make_account('T200004')
        helpers.login_account(self.client, 'T200004')

        with patch(
            'r22_account.middleware.resolve_identity',
            wraps=identity_module.resolve_identity,
        ) as spy:
            resp = self.client.get('/identity/')

        self.assertEqual(resp.status_code, 200)
        # 视图访问了 r22_identity / account / legacy_identity 三个入口
        self.assertEqual(spy.call_count, 1, '每请求只应解析一次')

    def test_auth_user_model_unchanged_under_r22_settings(self):
        from django.contrib.auth import get_user_model

        self.assertEqual(get_user_model()._meta.app_label, 'auth')
        self.assertEqual(settings.AUTH_USER_MODEL, 'auth.User')

    @override_settings(R22_FLAGS={'identity_mode': 'off', 'route_policy_enabled': True,
                                  'audit_enabled': True, 'dry_run': False})
    def test_mode_off_returns_anonymous(self):
        helpers.make_account('T200005')
        helpers.login_account(self.client, 'T200005')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'anonymous')
        self.assertEqual(payload['reason'], 'mode_off')
