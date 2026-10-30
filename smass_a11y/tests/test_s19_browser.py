"""S19 真实浏览器 E2E：键盘可达、焦点可见、窄屏无横向溢出。"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S19Browser#2026'


def make_account(login_name, roles, person_type='admin'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class S19BrowserA11yTests(StaticLiveServerTestCase):
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
        self.admin = make_account('S19E2EA', [RoleCode.SYSTEM_ADMIN])
        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.fill('input[name=login_name]', 'S19E2EA')
        self.page.fill('input[name=password]', PASSWORD)
        self.page.click('button[type=submit]')

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def test_skip_link_focus_and_zoom(self):
        self.page.goto(self.live_server_url + '/s19/')
        self.page.keyboard.press('Tab')

        focused = self.page.evaluate(
            "() => { const el = document.activeElement;"
            "return el ? el.textContent.trim() : ''; }")
        self.assertEqual('跳到主要内容', focused)

        outline = self.page.evaluate(
            "() => getComputedStyle(document.activeElement).outlineWidth")
        self.assertNotEqual('0px', outline, '焦点元素必须有可见轮廓')

        self.page.keyboard.press('Enter')
        self.assertIn('#main', self.page.url)

        # 320px 窄屏（相当于 200% 缩放的等效视口）不应出现横向滚动
        self.page.set_viewport_size({'width': 320, 'height': 640})
        overflow = self.page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth")
        self.assertLessEqual(overflow, 1, '窄屏出现横向溢出：{}'.format(overflow))

    def test_document_has_lang(self):
        self.page.goto(self.live_server_url + '/s19/')
        lang = self.page.evaluate("() => document.documentElement.lang")
        self.assertTrue(lang.startswith('zh'))
