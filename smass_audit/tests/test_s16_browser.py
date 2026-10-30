"""S16 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员查看审计链状态 → 扫描生成告警 → 在页面确认告警。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_audit import services
from smass_audit.models import SecurityAlert

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S16Browser#2026'


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
class S16BrowserFlowTests(StaticLiveServerTestCase):
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
        self.admin = make_account('S16E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('S16E2ES', [RoleCode.STUDENT])
        for _ in range(5):
            services.record(self.student, 'denied_action', result='denied')

        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def test_scan_and_ack_alert(self):
        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.fill('input[name=login_name]', 'S16E2EA')
        self.page.fill('input[name=password]', PASSWORD)
        self.page.click('button[type=submit]')

        self.page.goto(self.live_server_url + '/s16/events/')
        self.assertIn('哈希链', self.page.content())
        self.assertIn('完整', self.page.content())

        self.page.goto(self.live_server_url + '/s16/alerts/')
        self.page.click('form[action="/s16/alerts/scan/"] button[type=submit]')
        self.assertIn('扫描完成', self.page.content())
        self.assertIn('越权/拒绝突增', self.page.content())

        alert = SecurityAlert.objects.get()
        self.page.goto(self.live_server_url + '/s16/alerts/')
        self.page.click('form[action="/s16/alerts/{}/ack/"] button'.format(alert.pk))
        self.assertIn('告警已确认', self.page.content())

        alert.refresh_from_db()
        self.assertEqual(alert.status, 'acknowledged')
