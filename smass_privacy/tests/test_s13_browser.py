"""S13 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员登记隐私字段 → 学生申请披露 → 管理员批准 → 学生执行并下载脱敏 CSV。
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

from smass_privacy.models import DisclosureRequest

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S13Browser#2026'
PHONE = '13800001234'


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
class S13BrowserFlowTests(StaticLiveServerTestCase):
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
        StudentRecord.objects.create(
            student_no='S13E2E01', name='孙八', unit=self.klass,
            extra={'phone': PHONE})

        self.admin = make_account('S13E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('S13E2ES', [RoleCode.STUDENT])
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

    def test_configure_request_approve_and_download(self):
        context, admin = self._new_page('S13E2EA')
        try:
            admin.goto(self.live_server_url + '/s13/fields/')
            admin.fill('#field', 'phone')
            admin.select_option('#classification', 'personal')
            admin.select_option('#mask', 'none')
            admin.click('form[action="/s13/fields/save/"] button[type=submit]')
            self.assertIn('字段分级已保存', admin.content())
        finally:
            context.close()

        self._login(self.page, 'S13E2ES')
        self.page.goto(self.live_server_url + '/s13/disclosures/')
        self.page.check('input[name=fields][value=phone]')
        self.page.fill('#purpose', '浏览器披露')
        self.page.click('form[action="/s13/disclosures/new/"] button[type=submit]')
        self.assertIn('披露申请已提交', self.page.content())

        request_row = DisclosureRequest.objects.get()
        context, admin = self._new_page('S13E2EA')
        try:
            admin.goto(self.live_server_url + '/s13/disclosures/')
            admin.click('form[action="/s13/disclosures/{}/approve/"] button'.format(
                request_row.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        self.page.goto(self.live_server_url + '/s13/disclosures/')
        self.page.click('form[action="/s13/disclosures/{}/execute/"] button'.format(
            request_row.pk))
        self.assertIn('操作成功', self.page.content())

        request_row.refresh_from_db()
        self.assertEqual(request_row.status, 'executed')

        with self.page.expect_download() as download_info:
            self.page.click('a[href="/s13/disclosures/{}/export/"]'.format(
                request_row.pk))
        download = download_info.value
        with open(download.path(), 'rb') as handle:
            content = handle.read().decode('utf-8')
        self.assertIn('138****34', content)
        self.assertNotIn(PHONE, content)
