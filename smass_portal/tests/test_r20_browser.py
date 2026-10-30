"""R20 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员初始化门户并发布公告 → 学生登录看到学生门户入口与公告 →
教师登录看到教师门户。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_portal.models import PortalNotice

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R20Browser#2026'


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
class R20BrowserFlowTests(StaticLiveServerTestCase):
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
        self.admin = make_account('R20E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('R20E2ET', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('R20E2ES', [RoleCode.STUDENT])
        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def _login(self, page, login_name):
        page.goto(self.live_server_url + '/r20/login/')
        page.fill('input[name=login_name]', login_name)
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _new_page(self, login_name):
        context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(15000)
        self._login(page, login_name)
        return context, page

    def test_bootstrap_notice_and_role_portals(self):
        context, admin = self._new_page('R20E2EA')
        try:
            admin.goto(self.live_server_url + '/r20/admin/')
            admin.click('form[action="/r20/admin/bootstrap/"] button[type=submit]')
            self.assertIn('默认门户已初始化', admin.content())

            admin.fill('#notice_title', '浏览器门户公告')
            admin.fill('#notice_body', '公告内容')
            admin.fill('#notice_roles', 'student')
            admin.click('form[action="/r20/admin/notice/"] button[type=submit]')
            self.assertIn('公告已创建', admin.content())

            notice = PortalNotice.objects.get(title='浏览器门户公告')
            admin.goto(self.live_server_url + '/r20/admin/')
            admin.click('form[action="/r20/admin/notice/{}/publish/"] button'.format(
                notice.pk))
            self.assertIn('公告已发布', admin.content())
        finally:
            context.close()

        self._login(self.page, 'R20E2ES')
        self.page.goto(self.live_server_url + '/r20/')
        self.assertIn('学生门户', self.page.content())
        self.assertIn('浏览器门户公告', self.page.content())
        self.assertIn('转专业申请', self.page.content())

        context, teacher = self._new_page('R20E2ET')
        try:
            teacher.goto(self.live_server_url + '/r20/')
            self.assertIn('教师/辅导员门户', teacher.content())
        finally:
            context.close()
