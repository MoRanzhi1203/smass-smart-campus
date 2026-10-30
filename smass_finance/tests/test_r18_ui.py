"""R18 页面层：账单、合成缴费、受控退费与台账的页面流程。

运行::

    python manage.py test smass_finance.tests.test_r18_ui --settings=smass.settings_r18
"""
from __future__ import annotations

from decimal import Decimal

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_finance.models import Bill, FeeItem, LedgerEntry, RefundRequest

PASSWORD = 'R18Ui#2026'
LOGIN = '/r21/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


class FinanceUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('r18uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r18uistu', [RoleCode.STUDENT])
        self.student2 = make_account('r18uistu2', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9201', name='缴费学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S9202', name='其他学生', unit=self.klass, account=self.student2)

    def test_requires_login(self):
        response = self.client.get('/r18/bills/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_ledger(self):
        login(self.client, 'r18uistu')
        self.assertEqual(403, self.client.get('/r18/ledger/').status_code)

    def test_admin_creates_item_and_bill_via_page(self):
        admin = Client()
        login(admin, 'r18uiadmin')
        response = admin.post('/r18/fee-items/create/', {
            'code': 'FEE-UI', 'name': '界面学费', 'category': 'tuition',
            'amount': '3000.00', 'term': '2026-2027-1',
        })
        self.assertEqual(302, response.status_code)
        item = FeeItem.objects.get(code='FEE-UI')

        response = admin.post('/r18/bills/create/', {
            'record': self.me.pk, 'fee_item': item.pk, 'term': '2026-2027-1',
        })
        self.assertEqual(302, response.status_code)
        bill = Bill.objects.get(record=self.me)
        self.assertEqual(bill.total, Decimal('3000.00'))

    def test_admin_pays_via_page(self):
        item = FeeItem.objects.create(
            code='FEE-UI2', name='学费', category='tuition', amount=Decimal('3000.00'))
        bill = Bill.objects.create(
            bill_no='BILL-UI', record=self.me, total=Decimal('3000.00'),
            paid=Decimal('0.00'), status='unpaid')

        admin = Client()
        login(admin, 'r18uiadmin')
        response = admin.post('/r18/bills/{}/pay/'.format(bill.pk), {
            'amount': '1000.00', 'method': 'synthetic_bank', 'reference': 'UI-PAY-1',
        })
        self.assertEqual(302, response.status_code)
        bill.refresh_from_db()
        self.assertEqual(bill.paid, Decimal('1000.00'))
        self.assertEqual(bill.status, 'partial')

    def test_student_refund_flow_via_page(self):
        bill = Bill.objects.create(
            bill_no='BILL-UI3', record=self.me, total=Decimal('3000.00'),
            paid=Decimal('3000.00'), status='paid')

        login(self.client, 'r18uistu')
        response = self.client.post('/r18/bills/{}/refund/'.format(bill.pk), {
            'amount': '300.00', 'reason': '界面退费',
        })
        self.assertEqual(302, response.status_code)
        refund = RefundRequest.objects.get(bill=bill)

        admin = Client()
        login(admin, 'r18uiadmin')
        response = admin.post('/r18/refunds/{}/approve/'.format(refund.pk))
        self.assertEqual(302, response.status_code)
        response = admin.post('/r18/refunds/{}/execute/'.format(refund.pk))
        self.assertEqual(302, response.status_code)

        refund.refresh_from_db()
        bill.refresh_from_db()
        self.assertEqual(refund.status, 'paid')
        self.assertEqual(bill.paid, Decimal('2700.00'))
        self.assertTrue(LedgerEntry.objects.filter(
            bill=bill, entry_type='refund').exists())

    def test_student_sees_only_own_bills(self):
        Bill.objects.create(bill_no='BILL-A', record=self.me,
                            total=Decimal('100.00'), paid=Decimal('0.00'))
        Bill.objects.create(bill_no='BILL-B', record=self.other,
                            total=Decimal('200.00'), paid=Decimal('0.00'))
        login(self.client, 'r18uistu')
        response = self.client.get('/r18/bills/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'BILL-A')
        self.assertNotContains(response, 'BILL-B')

    def test_student_cannot_open_other_bill(self):
        bill = Bill.objects.create(bill_no='BILL-C', record=self.other,
                                   total=Decimal('100.00'), paid=Decimal('0.00'))
        login(self.client, 'r18uistu')
        self.assertEqual(403, self.client.get(
            '/r18/bills/{}/'.format(bill.pk)).status_code)
