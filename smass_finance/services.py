"""R18 服务层：收费项目、账单、合成缴费、受控退费与台账。

规则摘要
--------
- 账单由收费项目生成，生成时写一条"应收"台账；
- 缴费幂等（``reference`` 唯一），只允许未缴/部分缴纳的账单，金额不超过欠费；
- 退费三步：申请 → 审批（禁止自批）→ 出纳执行；执行时写负数台账并回写账单；
- 台账 append-only，任何修改/删除都会抛错；
- 全部为合成演练，不存在真实支付通道。
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    BILL_PAID,
    BILL_PARTIAL,
    BILL_REFUNDED,
    BILL_UNPAID,
    BILL_VOID,
    CATEGORY_OTHER,
    ENTRY_CHARGE,
    ENTRY_PAYMENT,
    ENTRY_REFUND,
    FEE_ACTIVE,
    FEE_CATEGORIES,
    METHOD_SYNTHETIC_BANK,
    PAYMENT_METHODS,
    PAYMENT_REFUNDED,
    PAYMENT_SUCCESS,
    REFUND_APPROVED,
    REFUND_PAID,
    REFUND_REJECTED,
    REFUND_SUBMITTED,
    Bill,
    BillItem,
    FeeItem,
    LedgerEntry,
    Payment,
    RefundRequest,
)

logger = logging.getLogger('smass.audit')

FINANCE_ROLES = frozenset({
    RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN,
})

ZERO = Decimal('0.00')


class FinanceError(ValueError):
    def __init__(self, message, code='FINANCE_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(FinanceError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def _decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        raise FinanceError('金额格式不合法', code='BAD_AMOUNT')


def can_finance(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & FINANCE_ROLES:
        return True
    return authz.has_action(account, 'update') and authz.has_action(
        account, 'manage_roles')


def _require_finance(account):
    if not can_finance(account):
        raise PermissionDenied('只有财务管理员可以执行该操作')


# ---------------------------------------------------------------------------
# 收费项目与账单
# ---------------------------------------------------------------------------
def create_fee_item(actor, code, name, category, amount, term=''):
    _require_finance(actor)
    if not str(code or '').strip() or not str(name or '').strip():
        raise FinanceError('项目编码与名称不能为空', code='EMPTY_FIELD')
    if category not in dict(FEE_CATEGORIES):
        raise FinanceError('未知的收费类别', code='BAD_CATEGORY')
    value = _decimal(amount)
    if value <= ZERO:
        raise FinanceError('收费金额必须大于 0', code='BAD_AMOUNT')
    if FeeItem.objects.filter(code=str(code).strip()).exists():
        raise FinanceError('项目编码已存在', code='DUPLICATE_CODE')

    item = FeeItem.objects.create(
        code=str(code).strip()[:64], name=str(name).strip()[:100],
        category=category, amount=value, term=str(term or '')[:32],
        status=FEE_ACTIVE)
    logger.info('fee_item_created id=%s code=%s by=%s',
                item.pk, item.code, _actor_id(actor))
    return item


def create_bill(record, term, fee_items, actor, *, due_date=None, bill_no=None):
    """按收费项目生成账单（合成数据）。"""
    _require_finance(actor)
    if record is None:
        raise FinanceError('学籍档案不存在', code='NO_RECORD')
    if not fee_items:
        raise FinanceError('至少选择一个收费项目', code='NO_FEE_ITEM')

    number = str(bill_no or '').strip() or 'BILL-{}-{}'.format(
        timezone.now().strftime('%Y%m%d%H%M%S'), uuid.uuid4().hex[:6])
    if Bill.objects.filter(bill_no=number).exists():
        raise FinanceError('账单号已存在', code='DUPLICATE_BILL')

    total = sum((item.amount for item in fee_items), ZERO)
    with transaction.atomic():
        bill = Bill.objects.create(
            bill_no=number[:64], record=record, term=str(term or '')[:32],
            total=total, paid=ZERO, status=BILL_UNPAID, due_date=due_date)
        for item in fee_items:
            BillItem.objects.create(bill=bill, fee_item=item, amount=item.amount)
        LedgerEntry.objects.create(
            entry_no='LED-{}-{}'.format(bill.pk, uuid.uuid4().hex[:8]),
            entry_type=ENTRY_CHARGE, bill=bill, amount=total, direction=1,
            operator=_actor_id(actor),
            note='生成账单 {}'.format(bill.bill_no))

    logger.info('bill_created id=%s no=%s total=%s by=%s',
                bill.pk, bill.bill_no, total, _actor_id(actor))
    return bill


def _refresh_bill_status(bill):
    if bill.paid <= ZERO:
        bill.status = BILL_UNPAID
    elif bill.paid < bill.total:
        bill.status = BILL_PARTIAL
    elif bill.paid == bill.total:
        bill.status = BILL_PAID
    else:
        bill.status = BILL_REFUNDED
    bill.save(update_fields=['paid', 'status', 'updated_at'])


# ---------------------------------------------------------------------------
# 缴费（合成）
# ---------------------------------------------------------------------------
def pay_bill(bill, amount, actor, *, method=METHOD_SYNTHETIC_BANK,
             reference=None, note=''):
    _require_finance(actor)
    value = _decimal(amount)
    if value <= ZERO:
        raise FinanceError('缴费金额必须大于 0', code='BAD_AMOUNT')
    if method not in dict(PAYMENT_METHODS):
        raise FinanceError('不支持的支付方式（仅合成演练）', code='BAD_METHOD')

    ref = str(reference or '').strip() or 'PAY-{}'.format(uuid.uuid4().hex)

    with transaction.atomic():
        existing = Payment.objects.filter(reference=ref).first()
        if existing is not None:
            return existing, False

        locked = Bill.objects.select_for_update().get(pk=bill.pk)
        if locked.status in (BILL_PAID, BILL_VOID, BILL_REFUNDED):
            raise FinanceError('该账单当前不能缴费（{}）'.format(locked.status),
                               code='BAD_STATE')
        outstanding = locked.total - locked.paid
        if value > outstanding:
            raise FinanceError(
                '缴费金额 {} 超过欠费 {}'.format(value, outstanding),
                code='OVERPAY')

        payment = Payment.objects.create(
            bill=locked, amount=value, method=method, status=PAYMENT_SUCCESS,
            reference=ref[:64], operator=_actor_id(actor),
            note=str(note or '')[:200])
        locked.paid = locked.paid + value
        _refresh_bill_status(locked)

        LedgerEntry.objects.create(
            entry_no='LED-P-{}'.format(uuid.uuid4().hex[:12]),
            entry_type=ENTRY_PAYMENT, bill=locked, amount=value, direction=1,
            operator=_actor_id(actor),
            note='合成缴费 {}'.format(payment.reference))

    logger.info('bill_paid bill=%s amount=%s ref=%s by=%s',
                bill.pk, value, ref, _actor_id(actor))
    return payment, True


# ---------------------------------------------------------------------------
# 退费
# ---------------------------------------------------------------------------
def _refunded_amount(bill):
    total = ZERO
    for refund in RefundRequest.objects.filter(bill=bill, status=REFUND_PAID):
        total += refund.amount
    return total


def request_refund(bill, amount, reason, actor):
    """退费申请：本人或财务发起。"""
    if bill is None:
        raise FinanceError('账单不存在', code='NO_BILL')
    is_owner = _is_self(actor, getattr(bill.record.account, 'pk', None))
    if not is_owner:
        _require_finance(actor)
    if not str(reason or '').strip():
        raise FinanceError('退费必须填写事由', code='EMPTY_REASON')
    value = _decimal(amount)
    if value <= ZERO:
        raise FinanceError('退费金额必须大于 0', code='BAD_AMOUNT')

    with transaction.atomic():
        locked = Bill.objects.select_for_update().get(pk=bill.pk)
        available = locked.paid - _refunded_amount(locked)
        pending = sum(
            (refund.amount for refund in RefundRequest.objects.filter(
                bill=locked, status__in=[REFUND_SUBMITTED, REFUND_APPROVED])),
            ZERO)
        if value > available - pending:
            raise FinanceError(
                '退费金额 {} 超过可退余额 {}'.format(value, available - pending),
                code='REFUND_EXCEEDED')

        refund = RefundRequest.objects.create(
            bill=locked, amount=value, reason=str(reason).strip()[:500],
            status=REFUND_SUBMITTED, submitted_by=_actor_id(actor))

    logger.info('refund_requested id=%s bill=%s amount=%s by=%s',
                refund.pk, bill.pk, value, _actor_id(actor))
    return refund


def approve_refund(refund, actor):
    _require_finance(actor)
    if refund.status != REFUND_SUBMITTED:
        raise FinanceError('只有待审批的退费可以批准', code='BAD_STATE')
    if _is_self(actor, refund.submitted_by):
        raise FinanceError('不能审批自己提交的退费（职责分离）',
                           code='SELF_APPROVAL_DENIED')
    refund.status = REFUND_APPROVED
    refund.reviewed_by = _actor_id(actor)
    refund.reviewed_at = timezone.now()
    refund.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    logger.info('refund_approved id=%s by=%s', refund.pk, _actor_id(actor))
    return refund


def reject_refund(refund, actor, reason):
    _require_finance(actor)
    if refund.status != REFUND_SUBMITTED:
        raise FinanceError('只有待审批的退费可以驳回', code='BAD_STATE')
    if _is_self(actor, refund.submitted_by):
        raise FinanceError('不能驳回自己提交的退费（职责分离）',
                           code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise FinanceError('驳回必须填写原因', code='EMPTY_REASON')
    refund.status = REFUND_REJECTED
    refund.reviewed_by = _actor_id(actor)
    refund.reviewed_at = timezone.now()
    refund.reject_reason = str(reason).strip()[:255]
    refund.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                               'reject_reason'])
    logger.info('refund_rejected id=%s by=%s', refund.pk, _actor_id(actor))
    return refund


def execute_refund(refund, actor):
    """出纳执行：写负向台账、回写账单与缴费记录。"""
    _require_finance(actor)
    if refund.status != REFUND_APPROVED:
        raise FinanceError('只有已批准的退费可以执行', code='BAD_STATE')

    with transaction.atomic():
        locked = RefundRequest.objects.select_for_update().get(pk=refund.pk)
        if locked.status != REFUND_APPROVED:
            raise FinanceError('该退费已处理', code='BAD_STATE')
        bill = Bill.objects.select_for_update().get(pk=locked.bill_id)
        if locked.amount > bill.paid:
            raise FinanceError('退费金额超过已缴金额', code='REFUND_EXCEEDED')

        bill.paid = bill.paid - locked.amount
        _refresh_bill_status(bill)
        LedgerEntry.objects.create(
            entry_no='LED-R-{}'.format(uuid.uuid4().hex[:12]),
            entry_type=ENTRY_REFUND, bill=bill, amount=locked.amount, direction=-1,
            operator=_actor_id(actor),
            note='退费 {}'.format(locked.pk))
        if bill.paid <= ZERO:
            Payment.objects.filter(bill=bill, status=PAYMENT_SUCCESS).update(
                status=PAYMENT_REFUNDED)

        locked.status = REFUND_PAID
        locked.paid_by = _actor_id(actor)
        locked.paid_at = timezone.now()
        locked.save(update_fields=['status', 'paid_by', 'paid_at'])

    logger.info('refund_paid id=%s bill=%s amount=%s by=%s',
                refund.pk, bill.pk, locked.amount, _actor_id(actor))
    return locked


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def scoped_bills(account):
    qs = Bill.objects.select_related('record')
    if can_finance(account):
        return qs.order_by('-created_at')
    record = None
    if getattr(account, 'pk', None) is not None:
        from smass_organization.models import StudentRecord
        record = StudentRecord.objects.filter(account=account).first()
    if record is None:
        return qs.none()
    return qs.filter(record=record).order_by('-created_at')


def scoped_refunds(account):
    qs = RefundRequest.objects.select_related('bill', 'bill__record')
    if can_finance(account):
        return qs.order_by('-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    from smass_organization.models import StudentRecord
    record = StudentRecord.objects.filter(account=account).first()
    if record is None:
        return qs.none()
    return qs.filter(bill__record=record).order_by('-created_at')


def scoped_ledger(account):
    if not can_finance(account):
        return LedgerEntry.objects.none()
    return LedgerEntry.objects.select_related('bill').order_by('-created_at')


def bill_summary(record):
    bills = Bill.objects.filter(record=record)
    total = sum((bill.total for bill in bills), ZERO)
    paid = sum((bill.paid for bill in bills), ZERO)
    return {'total': total, 'paid': paid, 'outstanding': total - paid,
            'count': bills.count()}


def finance_totals():
    bills = Bill.objects.all()
    total = sum((bill.total for bill in bills), ZERO)
    paid = sum((bill.paid for bill in bills), ZERO)
    refunded = sum(
        (refund.amount for refund in RefundRequest.objects.filter(status=REFUND_PAID)),
        ZERO)
    return {'total': total, 'paid': paid, 'outstanding': total - paid,
            'refunded': refunded}
