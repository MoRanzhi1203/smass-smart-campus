"""集成开发入口验收测试（``smass.settings_integrated_dev``）。

覆盖：
1. 统一入口 ``/hub/`` 未登录跳统一登录；
2. 管理员在 hub 看到并进入 R10 与 R11–R20 页面；
3. 角色差异：学生不能进 R12 分班管理（403），教师不能进 R11 排课规划（403）；
4. 旧系统（``smass.settings`` 默认入口 ``/login/``）不受影响；
5. 浏览器端到端：登录 → hub → 点击 R10 → 打开 R12。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.conf import settings as dj_settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

#: 本文件只对集成配置有意义；在其他 settings 下（如 R20 独立配置）整体跳过
IS_INTEGRATED = dj_settings.ROOT_URLCONF == 'smass.urls_integrated_dev'
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'Integrated#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='integrated-test')
    return Account.objects.get(pk=account.pk)


@unittest.skipUnless(IS_INTEGRATED, '仅在 smass.settings_integrated_dev 下运行')
class IntegratedEntryTests(TestCase):
    def setUp(self):
        self.admin = make_account('it_admin', [RoleCode.SYSTEM_ADMIN], 'admin')
        self.college = make_account('it_college', [RoleCode.COLLEGE_ADMIN], 'admin')
        self.teacher = make_account('it_teacher', [RoleCode.TEACHER], 'teacher')
        self.student = make_account('it_student', [RoleCode.STUDENT])

    def _login(self, login_name):
        client = Client()
        response = client.post('/r21/login/', {
            'login_name': login_name, 'password': PASSWORD})
        self.assertEqual(302, response.status_code)
        return client

    def test_hub_requires_login(self):
        response = self.client.get('/hub/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_root_redirects_to_hub(self):
        response = self.client.get('/')
        self.assertEqual(302, response.status_code)
        self.assertEqual('/hub/', response['Location'])

    def test_admin_hub_lists_all_groups(self):
        client = self._login('it_admin')
        response = client.get('/hub/')
        self.assertEqual(200, response.status_code)
        body = response.content.decode('utf-8')
        for label in ('R10 管理与运维', 'R12 自动分班与学籍异动',
                      'R20 多角色门户', 'R11 排课与课表'):
            self.assertIn(label, body)

    def test_admin_opens_r10_and_modules(self):
        client = self._login('it_admin')
        for path in ('/r10/', '/r4/units/', '/r12/placement/', '/r20/'):
            with self.subTest(path=path):
                self.assertEqual(200, client.get(path).status_code)

    def test_r10_requires_login_in_integrated(self):
        response = self.client.get('/r10/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_denied_placement(self):
        client = self._login('it_student')
        self.assertEqual(200, client.get('/hub/').status_code)
        self.assertEqual(403, client.get('/r12/placement/').status_code)

    def test_teacher_denied_plan_but_can_open_timetable(self):
        client = self._login('it_teacher')
        self.assertEqual(403, client.get('/r11/plan/').status_code)
        self.assertEqual(200, client.get('/r11/timetable/teacher/').status_code)

    def test_college_admin_can_open_r10(self):
        client = self._login('it_college')
        self.assertEqual(200, client.get('/r10/').status_code)

    def test_default_settings_untouched(self):
        """正式默认入口仍是旧系统：``smass.settings.ROOT_URLCONF == 'smass.urls'``。"""
        import smass.settings as default_settings

        self.assertEqual('smass.urls', default_settings.ROOT_URLCONF)


@unittest.skipUnless(IS_INTEGRATED, '仅在 smass.settings_integrated_dev 下运行')
@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class IntegratedBrowserTests(StaticLiveServerTestCase):
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
        self.admin = make_account('it_e2e_admin', [RoleCode.SYSTEM_ADMIN], 'admin')
        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def test_login_hub_then_r10_and_r12(self):
        self.page.goto(self.live_server_url + '/')
        self.assertIn('/hub/', self.page.url)
        self.assertIn('/r21/login/', self.page.url)

        self.page.fill('input[name=login_name]', 'it_e2e_admin')
        self.page.fill('input[name=password]', PASSWORD)
        self.page.click('button[type=submit]')
        self.assertIn('/hub/', self.page.url)
        self.assertIn('集成开发入口', self.page.content())

        self.page.goto(self.live_server_url + '/r10/')
        self.assertIn('学校管理平台', self.page.content())

        self.page.goto(self.live_server_url + '/r12/placement/')
        self.assertIn('分班', self.page.content())
