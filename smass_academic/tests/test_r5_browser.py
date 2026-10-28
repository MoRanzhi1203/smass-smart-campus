"""R5-06：浏览器 E2E（真实渲染 + 三端可见性 + 错误提示）。

引擎由 ``R5_BROWSER`` 选择（chromium/webkit/firefox）。
"""
import os
import unittest
from datetime import date

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services
from smass_academic.models import AcademicYear

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R5_BROWSER', 'chromium').strip().lower()
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

PASSWORD = 'R5E2E#2024'


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R5BrowserTests(StaticLiveServerTestCase):
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

        self.year = services.create_year(
            '2025-2026', date(2025, 9, 1), date(2026, 8, 31)
        )
        self.term = services.create_term(
            self.year, '1', date(2025, 9, 1), date(2026, 1, 15)
        )
        self.course = services.create_course('CS101', '程序设计', credit=3)
        self.section = services.create_section(self.term, self.course, 'A', capacity=30)
        self.section_b = services.create_section(self.term, self.course, 'B')

        self.admin = self._account('R5E_ADM', RoleCode.SYSTEM_ADMIN, 'admin')
        self.teacher = self._account('R5E_T', RoleCode.TEACHER, 'teacher')
        self.teacher2 = self._account('R5E_T2', RoleCode.TEACHER, 'teacher')
        self.student = self._account('R5E_S', RoleCode.STUDENT, 'student')

        services.assign_teacher(self.section, self.teacher, assigned_by='e2e')
        services.enroll(self.section, self.student, actor='e2e')

        self.context = None

    def _account(self, login, role, person_type):
        account = Account.objects.create_user(
            login, PASSWORD, display_name=login, person_type=person_type
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.grant_role(account, role, granted_by='r5_e2e')
        return Account.objects.get(pk=account.pk)

    def _page(self, viewport='desktop'):
        sizes = {'desktop': {'width': 1280, 'height': 860},
                 'mobile': {'width': 390, 'height': 844}}
        self.context = self.browser.new_context(viewport=sizes[viewport])
        page = self.context.new_page()
        page.set_default_timeout(15000)
        return page

    def _login(self, page, login, landing='/r5/years/'):
        account = Account.objects.get(login_name=login)
        self.client.force_login(account)
        page.context.add_cookies([{
            'name': 'sessionid',
            'value': self.client.session.session_key,
            'url': self.live_server_url,
        }])
        page.goto('{}{}'.format(self.live_server_url, landing))
        page.wait_for_load_state('load')

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    # ------------------------------------------------------------------
    def test_01_year_page_renders(self):
        page = self._page()
        self._login(page, 'R5E_ADM', '/r5/years/')

        body = page.content()
        self.assertIn('2025-2026', body)
        self.assertIsNotNone(page.query_selector('#year-table'))

    def test_02_course_page_renders(self):
        page = self._page()
        self._login(page, 'R5E_ADM', '/r5/courses/')

        body = page.content()
        self.assertIn('CS101', body)
        self.assertIn('程序设计', body)
        self.assertIsNotNone(page.query_selector('#course-table'))

    def test_03_section_page_renders(self):
        page = self._page()
        self._login(page, 'R5E_ADM', '/r5/sections/')

        body = page.content()
        self.assertIn('程序设计', body)   # 模板展示课程名称
        self.assertIsNotNone(page.query_selector('#section-table'))

    def test_04_teacher_workspace_only_own_sections(self):
        page = self._page()
        self._login(page, 'R5E_T', '/r5/workspace/')

        body = page.content()
        self.assertIn('A', body)
        self.assertIsNotNone(page.query_selector('#workspace-table'))

        # 未任课的 B 班不应出现在该教师工作台（通过 JSON 端点交叉验证）
        payload = page.evaluate(
            "() => fetch('/r5/workspace/', "
            "{headers: {'X-Requested-With': 'XMLHttpRequest'}})"
            ".then(r => r.json())"
        )
        codes = {row['code'] for row in payload['sections']}
        self.assertEqual(codes, {'A'})

    def test_05_student_my_courses(self):
        page = self._page()
        self._login(page, 'R5E_S', '/r5/my-courses/')

        body = page.content()
        self.assertIn('程序设计', body)   # 模板展示课程名称
        self.assertIsNotNone(page.query_selector('#my-table'))

    def test_06_mobile_viewport(self):
        page = self._page('mobile')
        self._login(page, 'R5E_S', '/r5/my-courses/')
        self.assertIn('程序设计', page.content())

    def test_07_invalid_term_range_shows_400(self):
        page = self._page()
        self._login(page, 'R5E_ADM', '/r5/years/')

        status = page.evaluate(
            """(yearId) => {
                const token = (document.cookie.split('; ')
                    .find(c => c.startsWith('csrftoken=')) || '').split('=')[1] || '';
                return fetch('/r5/terms/create/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': token,
                              'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({year: yearId, semester: '2',
                        start_date: '2020-01-01', end_date: '2020-06-01'})
                }).then(r => r.status);
            }""",
            self.year.pk,
        )
        self.assertEqual(status, 400)

    def test_08_unauthorized_role_cannot_see_year_page(self):
        page = self._page()
        self._login(page, 'R5E_S', '/r5/years/')

        body = page.content()
        self.assertIn('无权限', body)
