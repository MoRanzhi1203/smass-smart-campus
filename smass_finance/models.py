"""R18：学费账单、财务台账、对账与受控退费（隔离模块，全合成数据）。

设计约定
--------
1. **不接真实支付**：支付方式只有 ``synthetic_bank`` / ``synthetic_cash``，
   任何真实网关、真实退款都不在本模块范围内；
2. 账单金额由收费项目汇总，缴费与退费都必须写台账（append-only）；
3. **幂等缴费**：``Payment.reference`` 唯一，重复提交返回同一笔；
4. **受控退费**：申请 → 审批（禁止自批）→ 出纳执行，三步缺一不可；
5. 金额用 ``DecimalField``，禁止浮点；所有状态迁移在服务层校验。
"""
from __future__ import annotations

from django.db import models

# ---------------------------------------------------------------------------
# 收费项目
# ---------------------------------------------------------------------------
CATEGORY_TUITION = 'tuition'
CATEGORY_ACCOMMODATION = 'accommodation'
CATEGORY_TEXTBOOK = 'textbook'
CATEGORY_OTHER = 'other'
FEE_CATEGORIES = (
    (CATEGORY_TUITION, '学费'),
    (CATEGORY_ACCOMMODATION, '住宿费'),
    (CATEGORY_TEXTBOOK, '教材费'),
    (CATEGORY_OTHER, '其他'),
)

FEE_ACTIVE = 'active'
FEE_INACTIVE = 'inactive'


class FeeItem(models.Model):
    code = models.CharField('项目编码', max_length=64, unique=True)
    name = models.CharField('项目名称', max_length=100)
    category = models.CharField('类别', max_length=24, choices=FEE_CATEGORIES,
                                default=CATEGORY_TUITION)
    amount = models.DecimalField('金额', max_digits=10, decimal_places=2)
    term = models.CharField('学年学期', max_length=32, blank=True, default='')
    status = models.CharField('状态', max_length=16, default=FEE_ACTIVE)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '收费项目'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['term', 'status'])]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


# ---------------------------------------------------------------------------
# 账单
# ---------------------------------------------------------------------------
BILL_UNPAID = 'unpaid'
BILL_PARTIAL = 'partial'
BILL_PAID = 'paid'
BILL_REFUNDED = 'refunded'
BILL_VOID = 'void'
BILL_STATUS = (
    (BILL_UNPAID, '未缴'),
    (BILL_PARTIAL, '部分缴纳'),
    (BILL_PAID, '已缴清'),
    (BILL_REFUNDED, '已退费'),
    (BILL_VOID, '已作废'),
)


class Bill(models.Model):
    bill_no = models.CharField('账单号', max_length=64, unique=True)
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='finance_bills')
    term = models.CharField('学年学期', max_length=32, blank=True, default='')
    total = models.DecimalField('应缴金额', max_digits=10, decimal_places=2, default=0)
    paid = models.DecimalField('已缴金额', max_digits=10, decimal_places=2, default=0)
    status = models.CharField('状态', max_length=16, choices=BILL_STATUS,
                              default=BILL_UNPAID)
    due_date = models.DateField('缴费截止', null=True, blank=True)
    created_at = models.DateTimeField('生成时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '账单'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['record', 'status']),
            models.Index(fields=['term', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.bill_no, self.record.student_no)

    @property
    def outstanding(self):
        return (self.total or 0) - (self.paid or 0)


class BillItem(models.Model):
    bill = models.ForeignKey(
        Bill, verbose_name='账单', on_delete=models.CASCADE,
        related_name='items')
    fee_item = models.ForeignKey(
        FeeItem, verbose_name='收费项目', on_delete=models.PROTECT,
        related_name='bill_items')
    amount = models.DecimalField('金额', max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = '账单明细'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['bill', 'fee_item'], name='r18_uniq_bill_fee'),
        ]


# ---------------------------------------------------------------------------
# 缴费
# ---------------------------------------------------------------------------
METHOD_SYNTHETIC_BANK = 'synthetic_bank'
METHOD_SYNTHETIC_CASH = 'synthetic_cash'
PAYMENT_METHODS = (
    (METHOD_SYNTHETIC_BANK, '合成银行转账（演练）'),
    (METHOD_SYNTHETIC_CASH, '合成现金（演练）'),
)

PAYMENT_SUCCESS = 'success'
PAYMENT_FAILED = 'failed'
PAYMENT_REFUNDED = 'refunded'
PAYMENT_STATUS = (
    (PAYMENT_SUCCESS, '成功'),
    (PAYMENT_FAILED, '失败'),
    (PAYMENT_REFUNDED, '已退款'),
)


class Payment(models.Model):
    bill = models.ForeignKey(
        Bill, verbose_name='账单', on_delete=models.PROTECT,
        related_name='payments')
    amount = models.DecimalField('金额', max_digits=10, decimal_places=2)
    method = models.CharField('方式', max_length=24, choices=PAYMENT_METHODS,
                              default=METHOD_SYNTHETIC_BANK)
    status = models.CharField('状态', max_length=16, choices=PAYMENT_STATUS,
                              default=PAYMENT_SUCCESS)
    reference = models.CharField('幂等键', max_length=64, unique=True)
    operator = models.CharField('经办人', max_length=32, blank=True, default='')
    note = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('缴费时间', auto_now_add=True)

    class Meta:
        verbose_name = '缴费记录'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['bill', 'status'])]

    def __str__(self):
        return '{} {}'.format(self.reference, self.amount)


# ---------------------------------------------------------------------------
# 退费
# ---------------------------------------------------------------------------
REFUND_SUBMITTED = 'submitted'
REFUND_APPROVED = 'approved'
REFUND_REJECTED = 'rejected'
REFUND_PAID = 'paid'
REFUND_STATUS = (
    (REFUND_SUBMITTED, '待审批'),
    (REFUND_APPROVED, '已批准（待出纳）'),
    (REFUND_REJECTED, '已驳回'),
    (REFUND_PAID, '已退费'),
)


class RefundRequest(models.Model):
    bill = models.ForeignKey(
        Bill, verbose_name='账单', on_delete=models.PROTECT,
        related_name='refunds')
    amount = models.DecimalField('退费金额', max_digits=10, decimal_places=2)
    reason = models.CharField('退费事由', max_length=500)
    status = models.CharField('状态', max_length=16, choices=REFUND_STATUS,
                              default=REFUND_SUBMITTED)
    submitted_by = models.CharField('申请人', max_length=32, blank=True, default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    paid_by = models.CharField('出纳', max_length=32, blank=True, default='')
    paid_at = models.DateTimeField('退费时间', null=True, blank=True)
    created_at = models.DateTimeField('申请时间', auto_now_add=True)

    class Meta:
        verbose_name = '退费申请'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['bill', 'status']),
        ]

    def __str__(self):
        return '{} 退费 {}'.format(self.bill.bill_no, self.amount)


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------
ENTRY_CHARGE = 'charge'
ENTRY_PAYMENT = 'payment'
ENTRY_REFUND = 'refund'
ENTRY_ADJUST = 'adjust'
ENTRY_TYPES = (
    (ENTRY_CHARGE, '应收'),
    (ENTRY_PAYMENT, '实收'),
    (ENTRY_REFUND, '退费'),
    (ENTRY_ADJUST, '调整'),
)


class LedgerEntry(models.Model):
    """财务台账：append-only，不允许修改/删除。"""

    entry_no = models.CharField('流水号', max_length=64, unique=True)
    entry_type = models.CharField('类型', max_length=16, choices=ENTRY_TYPES)
    bill = models.ForeignKey(
        Bill, verbose_name='账单', null=True, blank=True,
        on_delete=models.PROTECT, related_name='ledger_entries')
    amount = models.DecimalField('金额', max_digits=10, decimal_places=2)
    direction = models.SmallIntegerField('方向（+1 收 / -1 退）', default=1)
    operator = models.CharField('经办人', max_length=32, blank=True, default='')
    note = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('记账时间', auto_now_add=True)

    class Meta:
        verbose_name = '财务台账'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['entry_type', '-created_at']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.entry_no, self.entry_type, self.amount)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('台账为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('台账为 append-only，不允许删除')
