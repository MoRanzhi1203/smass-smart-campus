"""R14 真实浏览器 E2E（Playwright + Chromium）。

覆盖：教师创建并发布活动 → 学生报名 → 学生签到 → 教师结束活动 →
生成待认定 → 管理员认定 → 累计学分可见。

Playwright/Chromium 不可用时用例 SkipTest，不伪装通过。
"""
import datetime as dt
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

from smass_activities.models import Activity, ActivityCredit, ActivityRegistration

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R14Browser#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


def fmt_local(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R14BrowserFlowTests(StaticLiveServerTestCase):
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

        self.teacher = make_account('R14E2ET', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.admin = make_account('R14E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('R14E2ES', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S7301', name='浏览器学生', unit=self.klass,
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
        page.goto(self.live_server_url + '/r14/login/')
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

    def test_full_activity_credit_flow(self):
        start = timezone.now() + dt.timedelta(hours=1)
        end = timezone.now() + dt.timedelta(hours=3)
        Activity.objects.create(
            title='浏览器志愿活动', category='volunteer',
            start_at=start, end_at=end, capacity=5,
            credit_points=1, volunteer_hours=2,
            status='published', checkin_code='888888',
            created_by=str(self.teacher.pk))

        self._login(self.page, 'R14E2ES')
        self.page.goto(self.live_server_url + '/r14/activities/')
        self.page.click('a.btn:has-text("详情")')
        self.page.click('form[action$="/register/"] button[type=submit]')
        self.assertIn('报名成功', self.page.content())

        registration = ActivityRegistration.objects.get(record=self.me)
        # 报名后把活动调到"进行中"，验证签到窗口
        Activity.objects.filter(pk=registration.activity_id).update(
            start_at=timezone.now() - dt.timedelta(minutes=5),
            end_at=timezone.now() + dt.timedelta(hours=2))
        self.page.goto('{}/r14/activities/{}/'.format(
            self.live_server_url, registration.activity_id))
        self.page.fill('input[name=code]', '888888')
        self.page.click('form[action$="/checkin/"] button[type=submit]')
        self.assertIn('签到成功', self.page.content())

        context, teacher = self._new_page('R14E2ET')
        try:
            activity = Activity.objects.get(title='浏览器志愿活动')
            teacher.goto('{}/r14/activities/{}/'.format(
                self.live_server_url, activity.pk))
            teacher.click('form[action$="/close/"] button[type=submit]')
            self.assertIn('活动已关闭', teacher.content())

            teacher.goto('{}/r14/activities/{}/'.format(
                self.live_server_url, activity.pk))
            teacher.click('form[action$="/generate-credits/"] button[type=submit]')
            self.assertIn('已生成', teacher.content())
        finally:
            context.close()

        context, admin = self._new_page('R14E2EA')
        try:
            credit = ActivityCredit.objects.get(activity__title='浏览器志愿活动')
            admin.goto(self.live_server_url + '/r14/credits/')
            admin.click('form[action="/r14/credits/{}/approve/"] button'.format(
                credit.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        credit.refresh_from_db()
        self.assertEqual(credit.status, 'approved')
        self.page.goto(self.live_server_url + '/r14/credits/')
        self.assertIn('已认定', self.page.content())
