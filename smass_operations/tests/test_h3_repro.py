"""H3：WebKit LiveServer 500 复现（最小案例）。

目标：在 `StaticLiveServerTestCase` 下用 WebKit 完成一次真实登录，
捕获 `/r21/login/` 的响应状态与服务端 traceback，用于定位
`Save with update_fields did not affect any rows` 的确切来源。

用法：
    R10_H3_ENGINE=webkit conda run -n smass python manage.py test \
        smass_operations.tests.test_h3_repro --settings=smass.settings_r10
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R10_H3_ENGINE', 'webkit').strip().lower()
PASSWORD = 'H3Pass#2024'


@unittest.skipIf(sync_playwright is None, 'playwright unavailable')
class WebKitLoginRepro(StaticLiveServerTestCase):
    host = '127.0.0.1'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, ENGINE, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('engine {} unavailable'.format(ENGINE))
        cls.browser = launcher.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        core_services.ensure_role_groups()
        account = Account.objects.create_user(
            'H3WEBKIT', PASSWORD, display_name='h3', person_type='admin')
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.grant_role(
            account, RoleCode.SYSTEM_ADMIN, granted_by='h3')
        self.account = Account.objects.get(pk=account.pk)
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 860})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def test_login_captures_status_and_traceback(self):
        responses = []
        self.page.on(
            'response',
            lambda r: responses.append((r.status, r.url))
            if '/r21/' in r.url else None,
        )

        console = []
        self.page.on('console', lambda m: console.append((m.type, m.text[:300])))

        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.wait_for_load_state('load')

        self.page.fill('#id_login_name', 'H3WEBKIT')
        self.page.fill('#id_password', PASSWORD)
        self.page.click('#btnLogin')
        self.page.wait_for_load_state('load')

        # 打印诊断（测试失败时可见）
        print('\n[H3] engine         :', ENGINE)
        print('[H3] final url      :', self.page.url)
        print('[H3] /r21 responses :', responses)
        print('[H3] console        :', console[-5:])

        login_codes = [status for status, url in responses if '/r21/login/' in url]
        print('[H3] login statuses:', login_codes)

        if 500 in login_codes:
            body = self.page.content()
            print('[H3] page snippet  :', body[:400].replace('\n', ' '))

        self.assertNotIn(
            500, login_codes,
            '{} 登录返回 500；responses={}'.format(ENGINE, responses),
        )

    def test_login_twice_in_sequence(self):
        """第二个测试：复用同一浏览器，验证 teardown/flush 后是否仍能登录。"""
        responses = []
        self.page.on(
            'response',
            lambda r: responses.append((r.status, r.url))
            if '/r21/' in r.url else None,
        )

        # 先访问一次业务页，制造服务器端连接活跃
        self.page.goto(self.live_server_url + '/r10/')
        self.page.wait_for_load_state('load')

        self.page.goto(self.live_server_url + '/r21/login/')
        self.page.wait_for_load_state('load')
        self.page.fill('#id_login_name', 'H3WEBKIT')
        self.page.fill('#id_password', PASSWORD)
        self.page.click('#btnLogin')
        self.page.wait_for_load_state('load')

        login_codes = [s for s, u in responses if '/r21/login/' in u]
        print('\n[H3-2] login statuses:', login_codes)
        print('[H3-2] final url     :', self.page.url)

        self.assertNotIn(500, login_codes, 'second test got 500: {}'.format(responses))
