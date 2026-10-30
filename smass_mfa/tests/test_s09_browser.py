"""S09 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员登录 → 被强制带到绑定页 → 输入 TOTP 完成绑定 → 看到恢复码 →
访问业务页被要求二次验证 → 输入 TOTP → 进入业务页。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_mfa import services
from smass_mfa.models import MfaDevice

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S09Browser#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class S09BrowserFlowTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        try:
            cls.browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('Chromium 启动失败：{}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.admin = make_account('S09E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def _login(self):
        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.fill('input[name=login_name]', 'S09E2EA')
        self.page.fill('input[name=password]', PASSWORD)
        self.page.click('button[type=submit]')

    def test_enroll_and_verify(self):
        self._login()
        self.page.goto(self.live_server_url + '/r21/home/')
        self.assertIn('/s09/setup/', self.page.url)

        device = MfaDevice.objects.get(account=self.admin)
        self.page.fill('input[name=code]', services.totp(device.secret))
        self.page.click('form[action="/s09/setup/"] button[type=submit]')
        self.assertIn('一次性恢复码', self.page.content())

        self.page.goto(self.live_server_url + '/r21/home/')
        self.assertIn('/r21/home/', self.page.url)

        # 退出后重新登录，必须二次验证
        self.page.goto(self.live_server_url + '/r21/logout/')
        self._login()
        self.page.goto(self.live_server_url + '/r21/home/')
        self.assertIn('/s09/verify/', self.page.url)

        device.refresh_from_db()
        self.page.fill('input[name=code]', services.totp(device.secret))
        self.page.click('form[action="/s09/verify/"] button[type=submit]')
        self.assertIn('/r21/home/', self.page.url)
        self.assertIn('S09E2EA', self.page.content())

        device.refresh_from_db()
        self.assertEqual(device.status, 'active')
