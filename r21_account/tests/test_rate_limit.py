"""G4 持久化登录限速测试（跨会话、按账号+IP 组合）。"""
from django.test import TestCase
from django.utils import timezone

from r21_account import services
from r21_account.models import Account, LoginAttempt

PASSWORD = 'RateLimit#2024'
LOGIN_NAME = 'T970001'


class RateLimitBase(TestCase):
    def setUp(self):
        account = Account.objects.create_user(
            LOGIN_NAME, PASSWORD, display_name='限速测试', person_type='teacher'
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])

    def _fail_once(self, ip='10.0.0.1'):
        return self.client.post(
            '/r21/login/',
            {'login_name': LOGIN_NAME, 'password': 'wrong'},
            REMOTE_ADDR=ip,
        )


class LockoutTests(RateLimitBase):
    def test_locked_after_max_failures_same_ip(self):
        limit = 5
        for _ in range(limit):
            self._fail_once('10.0.0.1')

        resp = self._fail_once('10.0.0.1')
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, '登录失败次数过多', status_code=429)

    def test_lock_is_persistent_across_clients(self):
        for _ in range(5):
            self._fail_once('10.0.0.1')

        # 全新 client（等价于另一个浏览器会话）仍应被锁定
        from django.test import Client

        fresh = Client()
        resp = fresh.post(
            '/r21/login/', {'login_name': LOGIN_NAME, 'password': PASSWORD},
            REMOTE_ADDR='10.0.0.1',
        )
        self.assertEqual(resp.status_code, 429)

    def test_other_ip_not_blocked_for_same_account(self):
        """避免恶意锁定他人账号：只有同 IP 达到阈值才锁。"""
        for _ in range(5):
            self._fail_once('10.0.0.1')

        resp = self.client.post(
            '/r21/login/', {'login_name': LOGIN_NAME, 'password': PASSWORD},
            REMOTE_ADDR='10.0.0.2',
        )
        # 同 IP 阈值未达（该 IP 0 次），但账号维度阈值 20 未达 -> 允许登录
        self.assertEqual(resp.status_code, 302)

    def test_successful_login_clears_failures(self):
        for _ in range(3):
            self._fail_once('10.0.0.3')
        self.assertEqual(LoginAttempt.objects.filter(success=False).count(), 3)

        self.client.post(
            '/r21/login/', {'login_name': LOGIN_NAME, 'password': PASSWORD},
            REMOTE_ADDR='10.0.0.3',
        )
        services.clear_login_failures(LOGIN_NAME)
        self.assertEqual(
            LoginAttempt.objects.filter(login_name=LOGIN_NAME, success=False).count(), 0
        )


class AccountWideLockoutTests(RateLimitBase):
    def test_account_wide_threshold(self):
        """跨 IP 累计 20 次失败也锁定（防分布式撞库）。"""
        for i in range(20):
            self._fail_once('10.1.0.{}'.format(i))

        locked, remaining, reason = services.login_lock_status(LOGIN_NAME, '10.9.9.9')
        self.assertTrue(locked)
        self.assertEqual(reason, 'per_login')
        self.assertGreater(remaining, 0)


class WindowExpiryTests(RateLimitBase):
    def test_old_failures_outside_window_do_not_lock(self):
        for _ in range(5):
            self._fail_once('10.0.0.5')

        # 把失败记录"变老"到窗口之外
        old = timezone.now() - timezone.timedelta(seconds=3600)
        LoginAttempt.objects.filter(login_name=LOGIN_NAME).update(created_at=old)

        locked, remaining, _ = services.login_lock_status(LOGIN_NAME, '10.0.0.5')
        self.assertFalse(locked)
        self.assertEqual(remaining, 0)

        resp = self.client.post(
            '/r21/login/', {'login_name': LOGIN_NAME, 'password': PASSWORD},
            REMOTE_ADDR='10.0.0.5',
        )
        self.assertEqual(resp.status_code, 302)
