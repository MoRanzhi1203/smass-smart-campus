"""S15 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员创建 API 客户端 → 签发令牌（页面仅展示一次）→ 吊销令牌。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_api_security.models import ApiClient, ApiToken

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S15Browser#2026'


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
class S15BrowserFlowTests(StaticLiveServerTestCase):
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
        self.admin = make_account('S15E2EA', [RoleCode.SYSTEM_ADMIN],
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

    def test_create_client_issue_and_revoke(self):
        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.fill('input[name=login_name]', 'S15E2EA')
        self.page.fill('input[name=password]', PASSWORD)
        self.page.click('button[type=submit]')

        self.page.goto(self.live_server_url + '/s15/')
        self.page.fill('#name', '浏览器客户端')
        self.page.click('form[action="/s15/clients/new/"] button[type=submit]')
        self.assertIn('客户端已创建', self.page.content())

        self.page.goto(self.live_server_url + '/s15/')
        client_obj = ApiClient.objects.get(name='浏览器客户端')
        self.page.select_option('select[name=client]', str(client_obj.pk))
        self.page.fill('#scopes', 'students:read')
        self.page.fill('#ttl', '600')
        self.page.click('form[action="/s15/tokens/new/"] button[type=submit]')
        self.assertIn('新令牌（仅显示一次）', self.page.content())

        token = ApiToken.objects.get()
        self.assertIn(token.token_hash[:10], self.page.content())

        self.page.goto(self.live_server_url + '/s15/')
        self.page.click('form[action="/s15/tokens/{}/revoke/"] button'.format(token.pk))
        self.assertIn('令牌已吊销', self.page.content())

        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
