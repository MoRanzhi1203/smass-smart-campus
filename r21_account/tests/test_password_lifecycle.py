"""G4 账号生命周期：强制改密、临时口令、密码策略。"""
from django.test import TestCase

from r21_account import services
from r21_account.models import Account

PASSWORD = 'InitPass#2024'


def make_account(login_name='T960001', must_change=True):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name='生命周期测试', person_type='teacher'
    )
    account.must_change_password = must_change
    account.save(update_fields=['must_change_password'])
    return account


class ForcePasswordChangeMiddlewareTests(TestCase):
    """must_change_password=True 时的访问限制（三端共用逻辑）。"""

    def setUp(self):
        self.account = make_account('T960001', must_change=True)

    def _login(self):
        resp = self.client.post(
            '/r21/login/', {'login_name': 'T960001', 'password': PASSWORD}
        )
        self.assertEqual(resp.status_code, 302)

    def test_home_redirects_to_change_password(self):
        self._login()
        resp = self.client.get('/r21/home/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/r21/change-password/')

    def test_ping_api_returns_403_json(self):
        self._login()
        resp = self.client.get('/r21/ping/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'must_change_password')

    def test_change_password_page_is_allowed(self):
        self._login()
        resp = self.client.get('/r21/change-password/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '首次登录须先修改密码')

    def test_cannot_bypass_by_direct_url(self):
        self._login()
        for path in ('/r21/home/', '/r21/ping/'):
            resp = self.client.get(path)
            self.assertIn(resp.status_code, (302, 403))

    def test_after_change_flag_cleared_and_access_allowed(self):
        self._login()
        resp = self.client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': 'AfterForce#2024',
            'confirm_password': 'AfterForce#2024',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '密码已更新')

        self.account.refresh_from_db()
        self.assertFalse(self.account.must_change_password)

        # 改密后应能正常进入首页（update_session_auth_hash 保证不被登出）
        home = self.client.get('/r21/home/')
        self.assertEqual(home.status_code, 200)

    def test_logout_always_allowed(self):
        self._login()
        resp = self.client.get('/r21/logout/')
        self.assertEqual(resp.status_code, 302)


class TemporaryPasswordTests(TestCase):
    def test_set_temporary_password_forces_change(self):
        account = make_account('T960002', must_change=False)
        services.set_temporary_password(account, 'Temp#2024')

        account.refresh_from_db()
        self.assertTrue(account.must_change_password)
        self.assertTrue(account.check_password('Temp#2024'))

    def test_temporary_password_marks_audit(self):
        account = make_account('T960003', must_change=False)
        services.set_temporary_password(account, 'Temp#2025')

        self.assertTrue(
            account.__class__ is Account
            and services.AccountAuditLog.objects.filter(
                action='password_reset', target='T960003'
            ).exists()
        )


class PasswordPolicyTests(TestCase):
    """统一使用 Django validate_password。"""

    def test_too_short_rejected(self):
        errors = services.password_policy_errors('Ab1')
        self.assertTrue(errors, '过短密码应被拒绝')

    def test_common_password_rejected(self):
        errors = services.password_policy_errors('password123')
        self.assertTrue(errors, '常见口令应被拒绝')

    def test_numeric_only_rejected(self):
        errors = services.password_policy_errors('123456789')
        self.assertTrue(errors, '纯数字应被拒绝')

    def test_strong_password_accepted(self):
        self.assertEqual(services.password_policy_errors('StrongPass#2024'), [])

    def test_long_password_has_no_upper_bound(self):
        """R2.1 取消学生端 6-10 位上限：20 位强密码应通过。"""
        long_password = 'Abcdefghij1234567890@'
        self.assertEqual(services.password_policy_errors(long_password), [])

    def test_change_password_rejects_weak(self):
        account = make_account('T960004', must_change=False)
        self.client.force_login(account)

        resp = self.client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': '123456',
            'confirm_password': '123456',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '密码')

        account.refresh_from_db()
        self.assertTrue(account.check_password(PASSWORD), '弱密码不应被写入')
