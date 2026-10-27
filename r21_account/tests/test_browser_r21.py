"""G5 浏览器验证：三端首次登录强制改密（Playwright + 隔离库）。

运行：
    conda run -n smass python manage.py test r21_account.tests.test_browser_r21 \
        --settings=smass.settings_r21 -v 2

若 Playwright/浏览器不可用则 SKIP（不伪装 PASS）。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services
from r21_account.models import Account, PersonType, RoleCode

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

TEMP_PASSWORD = 'TempPass#2024'
NEW_PASSWORD = 'ChangedPass#2024'


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class ForceChangeBrowserTests(StaticLiveServerTestCase):
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
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 860})
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        services.ensure_role_groups()

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    # ------------------------------------------------------------------
    def _make(self, login_name, person_type, role):
        account = Account.objects.create_user(
            login_name, TEMP_PASSWORD, display_name=login_name, person_type=person_type
        )
        services.set_temporary_password(account, TEMP_PASSWORD)
        services.grant_role(account, role, granted_by='e2e')
        account.refresh_from_db()
        return account

    def _login(self, login_name):
        self.page.goto('{}/r21/login/'.format(self.live_server_url))
        self.page.fill('#id_login_name', login_name)
        self.page.fill('#id_password', TEMP_PASSWORD)
        self.page.click('#btnLogin')
        self.page.wait_for_load_state('load')

    def _assert_forced_change_flow(self, login_name, person_type, role):
        self._make(login_name, person_type, role)
        self._login(login_name)

        # 登录后被强制改密中间件重定向
        self.assertIn('/r21/change-password/', self.page.url)
        self.assertIn('首次登录须先修改密码', self.page.content())

        # 直接访问首页也会被挡回改密页
        self.page.goto('{}/r21/home/'.format(self.live_server_url))
        self.page.wait_for_load_state('load')
        self.assertIn('/r21/change-password/', self.page.url)

        # 完成改密
        self.page.fill('#id_current', TEMP_PASSWORD)
        self.page.fill('#id_new', NEW_PASSWORD)
        self.page.fill('#id_confirm', NEW_PASSWORD)
        self.page.click('#btnChange')
        self.page.wait_for_load_state('load')
        self.assertIn('密码已更新', self.page.content())

        # 改密后可进入首页
        self.page.goto('{}/r21/home/'.format(self.live_server_url))
        self.page.wait_for_load_state('load')
        self.assertIn('/r21/home/', self.page.url)
        account = Account.objects.get(login_name=login_name)
        self.assertFalse(account.must_change_password)
        self.assertTrue(account.check_password(NEW_PASSWORD))

    def test_admin_forced_change(self):
        self._assert_forced_change_flow('E2E001', PersonType.ADMIN, RoleCode.SYSTEM_ADMIN)

    def test_teacher_forced_change(self):
        self._assert_forced_change_flow('E2E002', PersonType.TEACHER, RoleCode.TEACHER)

    def test_student_forced_change(self):
        self._assert_forced_change_flow('E2E003', PersonType.STUDENT, RoleCode.STUDENT)

    def test_weak_password_rejected_in_browser(self):
        self._make('E2E004', PersonType.TEACHER, RoleCode.TEACHER)
        self._login('E2E004')

        self.page.fill('#id_current', TEMP_PASSWORD)
        self.page.fill('#id_new', '123456')
        self.page.fill('#id_confirm', '123456')
        self.page.click('#btnChange')
        self.page.wait_for_load_state('load')

        account = Account.objects.get(login_name='E2E004')
        self.assertTrue(account.check_password(TEMP_PASSWORD), '弱密码不得被写入')
        self.assertTrue(account.must_change_password)
