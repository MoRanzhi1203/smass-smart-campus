"""R18 服务层：收费项目、账单、合成缴费、受控退费与台账。

运行::

    python manage.py test smass_finance.tests.test_r18_services --settings=smass.settings_r18
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_finance import services
from smass_finance.models import (
    Bill,
    FeeItem,
    LedgerEntry,
    Payment,
    RefundRequest,
)

PASSWORD = 'R18Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class FinanceBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('r18admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('r18stu', [RoleCode.STUDENT])
        self.student2 = make_account('r18stu2', [RoleCode.STUDENT])
        self.me = StudentRecord.objects.create(
            student_no='S9101', name='缴费学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S9102', name='其他学生', unit=self.klass, account=self.student2)

        self.tuition = services.create_fee_item(
            self.admin, 'FEE-TUITION', '学费', 'tuition', '5000.00', term='2026-2027-1')
        self.accommodation = services.create_fee_item(
            self.admin, 'FEE-DORM', '住宿费', 'accommodation', '1200.00',
            term='2026-2027-1')
        self.bill = services.create_bill(
            self.me, '2026-2027-1', [self.tuition, self.accommodation], self.admin)


class BillTests(FinanceBase):
    def test_fee_item_requires_finance(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_fee_item(self.student, 'FEE-X', '非法', 'other', '1.00')

    def test_fee_item_bad_amount(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_fee_item(self.admin, 'FEE-Z', '零元', 'other', '0')
        self.assertEqual(ctx.exception.code, 'BAD_AMOUNT')

    def test_duplicate_fee_code(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_fee_item(self.admin, 'FEE-TUITION', '重复', 'tuition', '1.00')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_CODE')

    def test_bill_total_and_ledger(self):
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.total, Decimal('6200.00'))
        self.assertEqual(self.bill.items.count(), 2)
        self.assertEqual(self.bill.status, 'unpaid')
        self.assertEqual(LedgerEntry.objects.filter(
            bill=self.bill, entry_type='charge').count(), 1)

    def test_bill_requires_items(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_bill(self.me, '2026-2027-1', [], self.admin)
        self.assertEqual(ctx.exception.code, 'NO_FEE_ITEM')


class PaymentTests(FinanceBase):
    def test_partial_then_full_payment(self):
        payment, created = services.pay_bill(self.bill, '2000.00', self.admin,
                                             reference='PAY-1')
        self.assertTrue(created)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid, Decimal('2000.00'))
        self.assertEqual(self.bill.status, 'partial')

        services.pay_bill(self.bill, '4200.00', self.admin, reference='PAY-2')
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid, Decimal('6200.00'))
        self.assertEqual(self.bill.status, 'paid')

    def test_idempotent_reference(self):
        first, created1 = services.pay_bill(self.bill, '1000.00', self.admin,
                                            reference='PAY-IDEM')
        second, created2 = services.pay_bill(self.bill, '1000.00', self.admin,
                                             reference='PAY-IDEM')
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first.pk, second.pk)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid, Decimal('1000.00'))

    def test_overpay_rejected(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.pay_bill(self.bill, '9000.00', self.admin, reference='PAY-OVER')
        self.assertEqual(ctx.exception.code, 'OVERPAY')
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid, Decimal('0.00'))

    def test_bad_method_rejected(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.pay_bill(self.bill, '100.00', self.admin,
                              method='real_gateway', reference='PAY-BAD')
        self.assertEqual(ctx.exception.code, 'BAD_METHOD')

    def test_pay_after_paid_rejected(self):
        services.pay_bill(self.bill, '6200.00', self.admin, reference='PAY-FULL')
        with self.assertRaises(services.FinanceError) as ctx:
            services.pay_bill(self.bill, '1.00', self.admin, reference='PAY-MORE')
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_student_cannot_pay(self):
        with self.assertRaises(services.PermissionDenied):
            services.pay_bill(self.bill, '100.00', self.student, reference='PAY-STU')

    def test_payment_writes_ledger(self):
        services.pay_bill(self.bill, '500.00', self.admin, reference='PAY-LED')
        entry = LedgerEntry.objects.get(bill=self.bill, entry_type='payment')
        self.assertEqual(entry.amount, Decimal('500.00'))
        self.assertEqual(entry.direction, 1)


class RefundTests(FinanceBase):
    def setUp(self):
        super().setUp()
        services.pay_bill(self.bill, '6200.00', self.admin, reference='PAY-BASE')
        self.bill.refresh_from_db()

    def test_refund_full_flow(self):
        refund = services.request_refund(self.bill, '1200.00', '住宿调整', self.student)
        self.assertEqual(refund.status, 'submitted')

        services.approve_refund(refund, self.admin)
        refund.refresh_from_db()
        self.assertEqual(refund.status, 'approved')

        services.execute_refund(refund, self.admin)
        refund.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(refund.status, 'paid')
        self.assertEqual(self.bill.paid, Decimal('5000.00'))
        self.assertEqual(self.bill.status, 'partial')

        entry = LedgerEntry.objects.get(bill=self.bill, entry_type='refund')
        self.assertEqual(entry.amount, Decimal('1200.00'))
        self.assertEqual(entry.direction, -1)

    def test_refund_exceeds_paid(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.request_refund(self.bill, '7000.00', '超额', self.student)
        self.assertEqual(ctx.exception.code, 'REFUND_EXCEEDED')

    def test_refund_empty_reason(self):
        with self.assertRaises(services.FinanceError) as ctx:
            services.request_refund(self.bill, '100.00', '  ', self.student)
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_self_approval_denied(self):
        refund = services.request_refund(self.bill, '100.00', '理由', self.admin)
        with self.assertRaises(services.FinanceError) as ctx:
            services.approve_refund(refund, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_student_cannot_approve(self):
        refund = services.request_refund(self.bill, '100.00', '理由', self.student)
        with self.assertRaises(services.PermissionDenied):
            services.approve_refund(refund, self.student)

    def test_pending_refund_counts_against_available(self):
        services.request_refund(self.bill, '6000.00', '大额', self.student)
        with self.assertRaises(services.FinanceError) as ctx:
            services.request_refund(self.bill, '500.00', '再来', self.student)
        self.assertEqual(ctx.exception.code, 'REFUND_EXCEEDED')

    def test_reject_requires_reason(self):
        refund = services.request_refund(self.bill, '100.00', '理由', self.student)
        with self.assertRaises(services.FinanceError) as ctx:
            services.reject_refund(refund, self.admin, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_execute_requires_approved(self):
        refund = services.request_refund(self.bill, '100.00', '理由', self.student)
        with self.assertRaises(services.FinanceError) as ctx:
            services.execute_refund(refund, self.admin)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')


class LedgerImmutabilityTests(FinanceBase):
    def test_ledger_cannot_be_modified(self):
        entry = LedgerEntry.objects.filter(bill=self.bill).first()
        entry.note = '改一下'
        with self.assertRaises(ValueError):
            entry.save()

    def test_ledger_cannot_be_deleted(self):
        entry = LedgerEntry.objects.filter(bill=self.bill).first()
        with self.assertRaises(ValueError):
            entry.delete()


class ScopingTests(FinanceBase):
    def test_student_sees_only_own_bills(self):
        services.create_bill(self.other, '2026-2027-1', [self.tuition], self.admin)
        self.assertEqual(services.scoped_bills(self.student).count(), 1)
        self.assertEqual(services.scoped_bills(self.admin).count(), 2)

    def test_student_sees_only_own_refunds(self):
        services.pay_bill(self.bill, '500.00', self.admin, reference='PAY-SCOPE')
        self.bill.refresh_from_db()
        services.request_refund(self.bill, '100.00', '理由', self.student)
        self.assertEqual(services.scoped_refunds(self.student).count(), 1)
        self.assertEqual(services.scoped_refunds(self.student2).count(), 0)

    def test_student_cannot_read_ledger(self):
        self.assertEqual(services.scoped_ledger(self.student).count(), 0)
        self.assertGreater(services.scoped_ledger(self.admin).count(), 0)

    def test_bill_summary(self):
        services.pay_bill(self.bill, '1000.00', self.admin, reference='PAY-SUM')
        self.bill.refresh_from_db()
        summary = services.bill_summary(self.me)
        self.assertEqual(summary['total'], Decimal('6200.00'))
        self.assertEqual(summary['paid'], Decimal('1000.00'))
        self.assertEqual(summary['outstanding'], Decimal('5200.00'))
