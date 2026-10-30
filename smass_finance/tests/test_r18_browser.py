"""R18 真实浏览器 E2E（Playwright + Chromium）。

覆盖：财务创建收费项目与账单 → 登记合成缴费 → 学生申请退费 →
财务批准并出纳执行 → 学生账单显示已缴/已退。

不接触任何真实支付通道。
"""
import os
import unittest
from decimal import Decimal

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

from smass_finance.models import Bill, FeeItem, RefundRequest

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R18Browser#2026'


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
class R18BrowserFlowTests(StaticLiveServerTestCase):
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

        self.admin = make_account('R18E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('R18E2ES', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9301', name='浏览器学生', unit=self.klass,
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
        page.goto(self.live_server_url + '/r18/login/')
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

    def test_bill_pay_and_refund(self):
        context, admin = self._new_page('R18E2EA')
        try:
            admin.goto(self.live_server_url + '/r18/bills/')
            admin.fill('input[name=code]', 'FEE-E2E')
            admin.fill('input[name=name]', '浏览器学费')
            admin.select_option('select[name=category]', 'tuition')
            admin.fill('input[name=amount]', '3000.00')
            admin.fill('input[name=term]', '2026-2027-1')
            admin.click('form[action="/r18/fee-items/create/"] button[type=submit]')
            self.assertIn('收费项目已创建', admin.content())

            item = FeeItem.objects.get(code='FEE-E2E')
            admin.goto(self.live_server_url + '/r18/bills/')
            admin.select_option('select[name=record]', str(self.me.pk))
            admin.select_option('select[name=fee_item]', str(item.pk))
            admin.fill('input[name=term]', '2026-2027-1')
            admin.click('form[action="/r18/bills/create/"] button[type=submit]')
            self.assertIn('账单已生成', admin.content())

            bill = Bill.objects.get(record=self.me)
            admin.goto('{}/r18/bills/{}/'.format(self.live_server_url, bill.pk))
            admin.fill('input[name=amount]', '3000.00')
            admin.fill('input[name=reference]', 'E2E-PAY-1')
            admin.click('form[action$="/pay/"] button[type=submit]')
            self.assertIn('合成缴费已登记', admin.content())
        finally:
            context.close()

        bill.refresh_from_db()
        self.assertEqual(bill.paid, Decimal('3000.00'))
        self.assertEqual(bill.status, 'paid')

        self._login(self.page, 'R18E2ES')
        self.page.goto('{}/r18/bills/{}/'.format(self.live_server_url, bill.pk))
        self.page.fill('input[name=amount]', '300.00')
        self.page.fill('input[name=reason]', '浏览器退费')
        self.page.click('form[action$="/refund/"] button[type=submit]')
        self.assertIn('退费申请已提交', self.page.content())

        refund = RefundRequest.objects.get(bill=bill)
        context, admin = self._new_page('R18E2EA')
        try:
            admin.goto(self.live_server_url + '/r18/refunds/')
            admin.click('form[action="/r18/refunds/{}/approve/"] button'.format(
                refund.pk))
            self.assertIn('操作成功', admin.content())
            admin.goto(self.live_server_url + '/r18/refunds/')
            admin.click('form[action="/r18/refunds/{}/execute/"] button'.format(
                refund.pk))
            self.assertIn('操作成功', admin.content())
        finally:
            context.close()

        refund.refresh_from_db()
        bill.refresh_from_db()
        self.assertEqual(refund.status, 'paid')
        self.assertEqual(bill.paid, Decimal('2700.00'))

        self.page.goto('{}/r18/bills/{}'.format(self.live_server_url, bill.pk))
        self.assertIn('2700.00', self.page.content())
