"""R17 真实浏览器 E2E（Playwright + Chromium）。

覆盖：学生发帖 → 另一学生举报 → 管理员在举报页下架 → 帖子对学生不可见。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_forum.models import Board, Post, Report

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R17Browser#2026'


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
class R17BrowserFlowTests(StaticLiveServerTestCase):
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
        self.admin = make_account('R17E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('R17E2ES', [RoleCode.STUDENT])
        self.student2 = make_account('R17E2ES2', [RoleCode.STUDENT])
        self.board = Board.objects.create(code='GENERAL', name='综合讨论')

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
        page.goto(self.live_server_url + '/r17/login/')
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

    def test_post_report_and_hide(self):
        self._login(self.page, 'R17E2ES')
        self.page.goto('{}/r17/forum/board/{}/'.format(
            self.live_server_url, self.board.pk))
        self.page.fill('input[name=title]', '浏览器帖子')
        self.page.fill('textarea[name=body]', '浏览器正文')
        self.page.click('form[action$="/post/"] button[type=submit]')
        self.assertIn('帖子已发布', self.page.content())

        post = Post.objects.get(title='浏览器帖子')

        context, other = self._new_page('R17E2ES2')
        try:
            other.goto('{}/r17/forum/post/{}/'.format(self.live_server_url, post.pk))
            other.fill('input[name=reason]', '内容不当')
            other.click('form[action="/r17/forum/report/"] button[type=submit]')
            self.assertIn('举报已提交', other.content())
        finally:
            context.close()

        report = Report.objects.get(target_id=post.pk)
        context, admin = self._new_page('R17E2EA')
        try:
            admin.goto(self.live_server_url + '/r17/reports/')
            admin.select_option('select[name=action]', 'hide')
            admin.click('form[action="/r17/reports/{}/resolve/"] button'.format(
                report.pk))
            self.assertIn('举报已处理', admin.content())
        finally:
            context.close()

        post.refresh_from_db()
        self.assertEqual(post.status, 'hidden')

        # 作者本人仍能看到自己的已下架帖子（设计如此），其他学生不应看到
        context, bystander = self._new_page('R17E2ES2')
        try:
            bystander.goto(self.live_server_url + '/r17/forum/')
            self.assertNotIn('浏览器帖子', bystander.content())
        finally:
            context.close()
        self.page.goto(self.live_server_url + '/r17/forum/')
        self.assertIn('已下架', self.page.content())
