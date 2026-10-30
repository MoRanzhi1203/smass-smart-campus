"""R13 真实浏览器 E2E（Playwright + Chromium）。

覆盖：教师创建考勤并看到签到码 → 学生登录签到 → 教师关闭会话 →
统计页显示出勤率；以及学生请假 → 教师批准。

Playwright/Chromium 不可用时用例 SkipTest，不伪装通过。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_attendance.models import AttendanceRecord, AttendanceSession, LeaveRequest

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R13Browser#2026'


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
class R13BrowserFlowTests(StaticLiveServerTestCase):
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
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('R13E2ET', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('R13E2ES', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S8001', name='浏览器学生', unit=self.klass,
            account=self.student)

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
        page.goto(self.live_server_url + '/r13/login/')
        page.fill('input[name=login_name]', login_name)
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _teacher_page(self):
        context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(15000)
        self._login(page, 'R13E2ET')
        return context, page

    def test_create_sign_close_and_stats(self):
        context, teacher = self._teacher_page()
        try:
            teacher.goto(self.live_server_url + '/r13/sessions/')
            teacher.select_option('select[name=unit]', str(self.klass.pk))
            teacher.fill('input[name=period]', '第1-2节')
            teacher.fill('input[name=topic]', '浏览器考勤')
            teacher.click('form[action="/r13/sessions/create/"] button[type=submit]')
            self.assertIn('考勤会话已创建', teacher.content())

            session = AttendanceSession.objects.get(unit=self.klass)
            self.assertEqual(len(session.code), 6)
        finally:
            context.close()

        self._login(self.page, 'R13E2ES')
        self.page.goto('{}/r13/sessions/{}/'.format(self.live_server_url, session.pk))
        self.page.fill('input[name=code]', session.code)
        self.page.click('form[action="/r13/sessions/{}/sign/"] button[type=submit]'.format(
            session.pk))
        self.assertIn('签到成功', self.page.content())

        context, teacher = self._teacher_page()
        try:
            teacher.goto('{}/r13/sessions/{}/'.format(self.live_server_url, session.pk))
            teacher.click('form[action="/r13/sessions/{}/close/"] button'.format(session.pk))
            self.assertIn('考勤已关闭', teacher.content())

            teacher.goto('{}/r13/stats/?unit={}'.format(
                self.live_server_url, self.klass.pk))
            self.assertIn('S8001', teacher.content())
        finally:
            context.close()

        session.refresh_from_db()
        self.assertEqual(session.status, 'closed')
        self.assertEqual(AttendanceRecord.objects.get(
            session=session, record=self.me).status, 'present')

    def test_leave_submit_and_approve(self):
        self._login(self.page, 'R13E2ES')
        self.page.goto(self.live_server_url + '/r13/leaves/')
        today = timezone.localdate().isoformat()
        self.page.fill('input[name=start_date]', today)
        self.page.fill('input[name=end_date]', today)
        self.page.fill('input[name=reason]', '浏览器请假')
        self.page.click('form[action="/r13/leaves/submit/"] button[type=submit]')
        self.assertIn('请假申请已提交', self.page.content())

        leave = LeaveRequest.objects.get(record=self.me)
        context, teacher = self._teacher_page()
        try:
            teacher.goto(self.live_server_url + '/r13/leaves/')
            teacher.click('form[action="/r13/leaves/{}/approve/"] button'.format(
                leave.pk))
            self.assertIn('操作成功', teacher.content())
        finally:
            context.close()

        leave.refresh_from_db()
        self.assertEqual(leave.status, 'approved')
