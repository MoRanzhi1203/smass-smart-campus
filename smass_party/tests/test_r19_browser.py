"""R19 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员建组织与敏感资料 → 学生访问被脱敏并申请借阅 →
管理员批准 → 学生可查看摘要，且访问审计留痕。
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

from smass_party.models import AccessLog, AccessRequest, PartyDocument, PartyOrg

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R19Browser#2026'


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
class R19BrowserFlowTests(StaticLiveServerTestCase):
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

        self.admin = make_account('R19E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('R19E2ES', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9601', name='浏览器学生', unit=self.klass,
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
        page.goto(self.live_server_url + '/r19/login/')
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

    def test_sensitive_document_request_and_approve(self):
        context, admin = self._new_page('R19E2EA')
        try:
            admin.goto(self.live_server_url + '/r19/orgs/')
            admin.fill('input[name=code]', 'BR-E2E')
            admin.fill('input[name=name]', '浏览器党支部')
            admin.select_option('select[name=org_type]', 'branch')
            admin.click('form[action="/r19/orgs/create/"] button[type=submit]')
            self.assertIn('组织已创建', admin.content())

            org = PartyOrg.objects.get(code='BR-E2E')
            admin.goto('{}/r19/orgs/{}/'.format(self.live_server_url, org.pk))
            admin.fill('#doc_title', '浏览器敏感资料')
            admin.select_option('#classification', 'sensitive')
            admin.fill('#doc_summary', '浏览器合成摘要')
            admin.click('form[action$="/documents/add/"] button[type=submit]')
            self.assertIn('资料已归档', admin.content())
        finally:
            context.close()

        document = PartyDocument.objects.get(title='浏览器敏感资料')

        self._login(self.page, 'R19E2ES')
        self.page.goto('{}/r19/documents/{}/'.format(
            self.live_server_url, document.pk))
        self.assertIn('受控资料', self.page.content())
        self.assertNotIn('浏览器合成摘要', self.page.content())

        self.page.fill('input[name=purpose]', '浏览器申请')
        self.page.click('form[action$="/request/"] button[type=submit]')
        self.assertIn('借阅申请已提交', self.page.content())

        request = AccessRequest.objects.get(document=document)
        context, admin = self._new_page('R19E2EA')
        try:
            admin.goto(self.live_server_url + '/r19/access/')
            admin.click('form[action="/r19/access/{}/approve/"] button'.format(
                request.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        self.page.goto('{}/r19/documents/{}/'.format(
            self.live_server_url, document.pk))
        self.assertIn('浏览器合成摘要', self.page.content())
        self.assertGreaterEqual(AccessLog.objects.filter(
            document=document).count(), 2)
