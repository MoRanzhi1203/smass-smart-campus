"""R7-03/05：浏览器验证（看板真实数值 + 越权拒绝 + 导出）。"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_analytics import services
from smass_organization import services as org_services
from smass_organization.models import OrganizationMembership, StudentRecord

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R7_BROWSER', 'chromium').strip().lower()
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

PASSWORD = 'R7E2E#2024'


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R7BrowserTests(StaticLiveServerTestCase):
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

        self.college_a = org_services.create_unit(code='RA', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(code='RB', name='B院', unit_type='college')
        for index in range(6):
            StudentRecord.objects.create(
                student_no='RA{:03d}'.format(index), name='A{}'.format(index),
                unit=self.college_a,
            )
        for index in range(2):
            StudentRecord.objects.create(
                student_no='RB{:03d}'.format(index), name='B{}'.format(index),
                unit=self.college_b,
            )

        self.sys = self._account('R7E_SYS', RoleCode.SYSTEM_ADMIN)
        self.admin_a = self._account('R7E_CA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)
        self.admin_b = self._account('R7E_CB', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_b, unit=self.college_b)

        services.validate_metric(services.register_metric(
            'org_units_total', '组织数', 'organization'))
        self.student_metric = services.register_metric(
            'students_scoped', '可见学生数', 'student')
        services.validate_metric(self.student_metric)

        self.report = services.create_report(
            'RPT_E2E', '看板报表',
            metric_codes=['org_units_total', 'students_scoped'],
            permission_roles=['system_admin'],
        )
        self.report.is_enabled = True
        self.report.save(update_fields=['is_enabled'])

        self.context = None

    def _account(self, login, role):
        account = Account.objects.create_user(
            login, PASSWORD, display_name=login, person_type='admin'
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.grant_role(account, role, granted_by='r7_e2e')
        return Account.objects.get(pk=account.pk)

    def _page(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 860})
        page = self.context.new_page()
        page.set_default_timeout(15000)
        return page

    def _login(self, page, login, landing='/r7/dashboard/'):
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

    def test_01_dashboard_renders_real_values(self):
        page = self._page()
        self._login(page, 'R7E_SYS')

        body = page.content()
        self.assertIn('org_units_total', body)
        self.assertIn('students_scoped', body)
        self.assertIsNotNone(page.query_selector('#dashboard-table'))

        payload = page.evaluate(
            "() => fetch('/r7/dashboard/', "
            "{headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.json())"
        )
        values = {row['metric']: row['value'] for row in payload['rows']}
        self.assertEqual(int(values['org_units_total']), 2)      # A院 + B院
        self.assertEqual(int(values['students_scoped']), 8)      # 6 + 2

    def test_02_metric_list_renders(self):
        page = self._page()
        self._login(page, 'R7E_SYS', '/r7/metrics/')

        body = page.content()
        self.assertIn('org_units_total', body)
        self.assertIsNotNone(page.query_selector('#metric-table'))

    def test_03_college_admin_sees_only_own_scope(self):
        page = self._page()
        self._login(page, 'R7E_CA')

        payload = page.evaluate(
            "() => fetch('/r7/dashboard/', "
            "{headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.json())"
        )
        values = {row['metric']: row['value'] for row in payload['rows']}
        # A 院 6 人 >= 阈值 5，可见
        self.assertEqual(int(values['students_scoped']), 6)

    def test_04_small_group_suppressed_in_browser(self):
        page = self._page()
        self._login(page, 'R7E_CB')

        payload = page.evaluate(
            "() => fetch('/r7/dashboard/', "
            "{headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.json())"
        )
        values = {row['metric']: row['value'] for row in payload['rows']}
        # B 院 2 人 < 阈值 5 -> 抑制为 0
        self.assertEqual(int(values['students_scoped']), 0)

    def test_05_report_export_returns_csv_with_hash(self):
        page = self._page()
        self._login(page, 'R7E_SYS')

        result = page.evaluate(
            "() => fetch('/r7/reports/RPT_E2E/export/')"
            ".then(r => r.text().then(t => ({status: r.status, body: t})))"
        )
        self.assertEqual(result['status'], 200)
        self.assertIn('query_hash', result['body'])

    def test_06_unauthorized_report_rejected(self):
        page = self._page()
        self._login(page, 'R7E_CA')   # 报表只授权 system_admin

        result = page.evaluate(
            "() => fetch('/r7/reports/RPT_E2E/run/')"
            ".then(r => ({status: r.status}))"
        )
        self.assertEqual(result['status'], 403)
