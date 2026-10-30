"""S10 真实浏览器 E2E（Playwright + Chromium）。

覆盖：发起人再认证并发起敏感操作 → 另一管理员批准 → 发起人执行 →
执行日志出现。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_stepup.models import DualApproval, OperationLog

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S10Browser#2026'


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
class S10BrowserFlowTests(StaticLiveServerTestCase):
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
        self.admin_a = make_account('S10E2EA', [RoleCode.SYSTEM_ADMIN],
                                    person_type='admin')
        self.admin_b = make_account('S10E2EB', [RoleCode.SYSTEM_ADMIN],
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

    def _login(self, page, login_name):
        page.goto(self.live_server_url + '/r21/login/')
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

    def test_stepup_two_person_flow(self):
        self._login(self.page, 'S10E2EA')
        self.page.goto(self.live_server_url + '/s10/verify/?action=export_sensitive')
        self.page.select_option('select[name=action_code]', 'export_sensitive')
        self.page.select_option('select[name=method]', 'password')
        self.page.fill('input[name=code]', PASSWORD)
        self.page.click('form[action="/s10/verify/submit/"] button[type=submit]')
        self.assertIn('再认证成功', self.page.content())

        self.page.goto(self.live_server_url + '/s10/')
        row = self.page.locator('tr', has_text='导出敏感数据')
        row.locator('input[name=target]').fill('S-100')
        row.locator('input[name=reason]').fill('浏览器双人审批')
        row.locator('button[type=submit]').click()
        self.assertIn('工单已创建', self.page.content())

        approval = DualApproval.objects.get()
        context, approver = self._new_page('S10E2EB')
        try:
            approver.goto(self.live_server_url + '/s10/approvals/')
            approver.click(
                'form[action="/s10/approvals/{}/approve/"] button'.format(approval.pk))
            self.assertIn('操作成功', approver.content())
        finally:
            context.close()

        self.page.goto(self.live_server_url + '/s10/approvals/')
        self.page.click(
            'form[action="/s10/approvals/{}/execute/"] button'.format(approval.pk))
        self.assertIn('操作成功', self.page.content())

        approval.refresh_from_db()
        self.assertEqual(approval.status, 'executed')
        self.assertEqual(OperationLog.objects.filter(
            approval_id=approval.pk).count(), 1)
        self.assertIn('已执行', self.page.content())
