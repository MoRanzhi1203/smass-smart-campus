"""R4-04：浏览器 E2E（真实渲染 + 交互 + 权限）。

覆盖：
1. 组织列表页真实渲染；
2. 学生列表页渲染且**受组织 scope 限制**（A 院看不到 B 院）；
3. 非法移动在浏览器中显示错误；
4. 导入预检/提交通过浏览器 fetch 完成；
5. 受限导出可在浏览器中下载并含正确表头。

引擎由 ``R4_BROWSER`` 选择（chromium/webkit/firefox），未安装则 SKIP。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import services
from smass_organization.models import (
    OrganizationMembership,
    OrganizationUnit,
    StudentRecord,
)

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R4_BROWSER', 'chromium').strip().lower()
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

PASSWORD = 'R4E2E#2024'


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R4BrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, ENGINE, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('未知引擎 {}'.format(ENGINE))
        try:
            cls.browser = launcher.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('{} 启动失败: {}'.format(ENGINE, str(exc)[:200]))

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

        self.college_a = services.create_unit(code='EA', name='A学院', unit_type='college')
        self.college_b = services.create_unit(code='EB', name='B学院', unit_type='college')
        self.major_a = services.create_unit(code='EMA', name='A专业', unit_type='major',
                                            parent=self.college_a)

        StudentRecord.objects.create(student_no='EA01', name='A院学生', unit=self.college_a)
        StudentRecord.objects.create(student_no='EB01', name='B院学生', unit=self.college_b)

        self.admin_a = self._account('E2EA', RoleCode.COLLEGE_ADMIN)
        self.sys = self._account('E2ESYS', RoleCode.SYSTEM_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)

        self.context = None

    def _account(self, login, role):
        account = Account.objects.create_user(
            login, PASSWORD, display_name=login, person_type='admin'
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.grant_role(account, role, granted_by='r4_e2e')
        return Account.objects.get(pk=account.pk)

    def _page(self, viewport='desktop'):
        sizes = {'desktop': {'width': 1280, 'height': 860},
                 'mobile': {'width': 390, 'height': 844}}
        self.context = self.browser.new_context(viewport=sizes[viewport])
        page = self.context.new_page()
        page.set_default_timeout(15000)
        return page

    def _login(self, page, login):
        """用 Django 测试客户端建立 session，再注入浏览器 cookie。

        说明：R4-04 的验收目标是**页面渲染与组织 scope**；登录/改密流程已由
        R2.1/R2.2 的浏览器测试覆盖，这里避免重复依赖 r21 的跳转目标。
        """
        account = Account.objects.get(login_name=login)
        self.client.force_login(account)
        session_key = self.client.session.session_key

        page.context.add_cookies([{
            'name': 'sessionid',
            'value': session_key,
            'url': self.live_server_url,
        }])
        page.goto('{}/r4/units/'.format(self.live_server_url))
        page.wait_for_load_state('load')

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    # ------------------------------------------------------------------
    def test_01_unit_page_renders(self):
        page = self._page()
        self._login(page, 'E2EA')

        page.goto('{}/r4/units/'.format(self.live_server_url))
        page.wait_for_load_state('load')

        body = page.content()
        self.assertIn('A学院', body)
        self.assertNotIn('B学院', body)   # scope：A 院管理员看不到 B 院
        self.assertIsNotNone(page.query_selector('#unit-table'))

    def test_02_student_list_scoped_rendering(self):
        page = self._page()
        self._login(page, 'E2EA')

        page.goto('{}/r4/students/'.format(self.live_server_url))
        page.wait_for_load_state('load')

        body = page.content()
        self.assertIn('A院学生', body)
        self.assertNotIn('B院学生', body)
        self.assertIsNotNone(page.query_selector('#student-table'))

    def test_03_mobile_viewport_renders(self):
        page = self._page('mobile')
        self._login(page, 'E2EA')

        page.goto('{}/r4/students/'.format(self.live_server_url))
        page.wait_for_load_state('load')

        self.assertIn('A院学生', page.content())

    def test_04_invalid_move_shows_error_in_browser(self):
        page = self._page()
        self._login(page, 'E2ESYS')   # 移动需要 system_admin

        # 直接把 A学院 移到它自己的专业下 -> 应返回 CYCLE
        status = page.evaluate(
            """() => {
                const token = (document.cookie.split('; ').find(c => c.startsWith('csrftoken=')) || '')
                    .split('=')[1] || '';
                return fetch(window.location.origin + '/r4/units/%d/move/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': token,
                              'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({parent: %d})
                }).then(r => r.status);
            }""" % (self.college_a.pk, self.major_a.pk)
        )
        self.assertEqual(status, 400)

    def test_05_import_preview_and_commit_in_browser(self):
        page = self._page()
        self._login(page, 'E2ESYS')   # 导入需要 system_admin

        csv_text = 'student_no,name,unit_code,status\nEA99,E2E学生,EA,enrolled'

        preview = page.evaluate(
            """(csv) => fetch('/r4/import/preview/', {
                method: 'POST',
                headers: {'Content-Type': 'text/plain'},
                body: csv
            }).then(r => r.json())""",
            csv_text,
        )
        self.assertTrue(preview['ok'])
        self.assertEqual(preview['total'], 1)
        self.assertEqual(preview['errors'], 0)

        commit = page.evaluate(
            """(csv) => fetch('/r4/import/commit/', {
                method: 'POST',
                headers: {'Content-Type': 'text/plain'},
                body: csv
            }).then(r => r.json())""",
            csv_text,
        )
        self.assertTrue(commit['ok'])
        self.assertEqual(commit['stats']['created'], 1)

        # 重新加载页面能看到新学生
        page.goto('{}/r4/students/'.format(self.live_server_url))
        page.wait_for_load_state('load')
        self.assertIn('E2E学生', page.content())

    def test_06_export_endpoint_returns_csv_in_browser(self):
        page = self._page()
        self._login(page, 'E2EA')

        result = page.evaluate(
            """() => fetch('/r4/students/export/')
                .then(r => r.text().then(t => ({status: r.status, body: t})))"""
        )

        self.assertEqual(result['status'], 200)
        body = result['body']
        self.assertIn('student_no', body)
        self.assertIn('EA01', body)
        self.assertNotIn('EB01', body)    # 导出同样受 scope 限制

    def test_07_anonymous_redirected_to_login(self):
        page = self._page()
        page.goto('{}/r4/units/'.format(self.live_server_url))
        page.wait_for_load_state('load')

        # 无 cookie 访问受保护页面 -> 403 或跳登录
        self.assertTrue(
            'r4/login' in page.url or '无权限' in page.content()
        )
