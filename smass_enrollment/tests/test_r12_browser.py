"""R12 真实浏览器 E2E（Playwright + Chromium）。

覆盖三条真实业务链：

1. 学生提交转专业 → 管理员批准 → 编入目标班级生效；
2. 管理员分班：生成预览 → 执行 → 学籍档案班级变更；
3. 学生提交学籍异动 → 管理员批准 → 确认生效（状态变更）。

Playwright/Chromium 不可用时用例会 SkipTest，不伪装通过。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_enrollment.models import (
    MajorTransferRequest,
    PlacementBatch,
    PlacementRule,
    StudentStatusChange,
)

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R12Browser#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


def make_unit(code, name, unit_type, parent=None):
    return OrganizationUnit.objects.create(
        code=code, name=name, unit_type=unit_type, parent=parent)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R12BrowserFlowTests(StaticLiveServerTestCase):
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
        self.college = make_unit('C01', '计算机学院', UNIT_TYPE_COLLEGE)
        self.major_cs = make_unit('M01', '计算机科学与技术', UNIT_TYPE_MAJOR, self.college)
        self.major_se = make_unit('M02', '软件工程', UNIT_TYPE_MAJOR, self.college)
        self.class_cs1 = make_unit('CL01', '计科一班', UNIT_TYPE_CLASS, self.major_cs)
        self.class_se1 = make_unit('CL11', '软工一班', UNIT_TYPE_CLASS, self.major_se)

        self.student = make_account('R12E2ES', [RoleCode.STUDENT])
        make_account('R12E2EA', [RoleCode.SYSTEM_ADMIN], person_type='admin')
        self.record = StudentRecord.objects.create(
            student_no='S9001', name='浏览器学生', unit=self.class_cs1,
            account=self.student)
        self.rule = PlacementRule.objects.create(
            name='E2E 分班规则', major=self.major_cs, capacity_per_class=0,
            strategy='round_robin')

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
        page.goto(self.live_server_url + '/r12/login/')
        page.fill('input[name=login_name]', login_name)
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _admin_page(self):
        context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(15000)
        self._login(page, 'R12E2EA')
        return context, page

    def test_transfer_submit_approve_apply(self):
        self._login(self.page, 'R12E2ES')
        self.page.goto(self.live_server_url + '/r12/transfers/')
        self.page.select_option('select[name=to_major]', str(self.major_se.pk))
        self.page.fill('input[name=reason]', '浏览器转专业')
        self.page.click('form[action="/r12/transfers/submit/"] button[type=submit]')
        self.assertIn('转专业申请已提交', self.page.content())

        transfer = MajorTransferRequest.objects.get(record=self.record)
        context, admin = self._admin_page()
        try:
            admin.goto(self.live_server_url + '/r12/transfers/')
            admin.click(
                'form[action="/r12/transfers/{}/approve/"] button'.format(transfer.pk))
            self.assertIn('操作成功', admin.content())

            admin.goto(self.live_server_url + '/r12/transfers/')
            admin.select_option(
                'form[action="/r12/transfers/{}/apply/"] select[name=target_class]'.format(
                    transfer.pk), str(self.class_se1.pk))
            admin.click(
                'form[action="/r12/transfers/{}/apply/"] button'.format(transfer.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        transfer.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(transfer.status, 'effective')
        self.assertEqual(self.record.unit_id, self.class_se1.pk)

    def test_placement_preview_and_apply(self):
        StudentRecord.objects.create(
            student_no='S9101', name='待分班一', unit=self.major_cs)
        StudentRecord.objects.create(
            student_no='S9102', name='待分班二', unit=self.major_cs)

        context, admin = self._admin_page()
        try:
            admin.goto(self.live_server_url + '/r12/placement/')
            admin.click(
                'form[action="/r12/placement/preview/{}/"] button'.format(self.rule.pk))
            self.assertIn('已生成预览', admin.content())

            batch = PlacementBatch.objects.latest('pk')
            admin.click(
                'form[action="/r12/placement/{}/apply/"] button'.format(batch.pk))
            self.assertIn('分班已执行', admin.content())
        finally:
            context.close()

        batch.refresh_from_db()
        self.assertEqual(batch.status, 'applied')
        self.assertEqual(
            StudentRecord.objects.get(student_no='S9101').unit.unit_type,
            UNIT_TYPE_CLASS)

    def test_status_change_submit_approve_apply(self):
        self._login(self.page, 'R12E2ES')
        self.page.goto(self.live_server_url + '/r12/status/')
        self.page.select_option('select[name=change_type]', 'suspend')
        self.page.fill('input[name=reason]', '浏览器休学')
        self.page.click('form[action="/r12/status/submit/"] button[type=submit]')
        self.assertIn('学籍异动申请已提交', self.page.content())

        change = StudentStatusChange.objects.get(record=self.record)
        context, admin = self._admin_page()
        try:
            admin.goto(self.live_server_url + '/r12/status/')
            admin.click(
                'form[action="/r12/status/{}/approve/"] button'.format(change.pk))
            admin.goto(self.live_server_url + '/r12/status/')
            admin.click(
                'form[action="/r12/status/{}/apply/"] button'.format(change.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        change.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual(change.status, 'effective')
        self.assertEqual(self.record.status, 'suspended')
