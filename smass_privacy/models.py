"""S13：数据最小化、保留控制与受控披露（隔离模块）。

机制
----
1. **字段分级**：每个资源字段标注 ``public/internal/sensitive/personal``、
   保留天数与导出脱敏方式；
2. **最小化导出**：导出只包含已登记字段，``sensitive/personal`` 默认脱敏；
3. **受控披露**：导出必须先申请 → 审批（禁止自批）→ 执行；执行生成 CSV 文本、
   计算 SHA-256 并写披露日志（append-only）；
4. **保留控制**：``purge_expired`` 按 ``retention_days`` 清理超过保留期的样本数据。
"""
from __future__ import annotations

from django.db import models

CLASSIFICATION_PUBLIC = 'public'
CLASSIFICATION_INTERNAL = 'internal'
CLASSIFICATION_SENSITIVE = 'sensitive'
CLASSIFICATION_PERSONAL = 'personal'
CLASSIFICATIONS = (
    (CLASSIFICATION_PUBLIC, '公开'),
    (CLASSIFICATION_INTERNAL, '内部'),
    (CLASSIFICATION_SENSITIVE, '敏感'),
    (CLASSIFICATION_PERSONAL, '个人隐私'),
)

MASK_NONE = 'none'
MASK_PARTIAL = 'partial'
MASK_FULL = 'full'
MASK_CHOICES = (
    (MASK_NONE, '不脱敏'),
    (MASK_PARTIAL, '部分脱敏'),
    (MASK_FULL, '完全遮挡'),
)


class DataField(models.Model):
    resource = models.CharField('资源', max_length=64)
    field = models.CharField('字段', max_length=64)
    classification = models.CharField('分级', max_length=16,
                                       choices=CLASSIFICATIONS,
                                       default=CLASSIFICATION_INTERNAL)
    mask = models.CharField('导出脱敏', max_length=16, choices=MASK_CHOICES,
                            default=MASK_NONE)
    retention_days = models.PositiveIntegerField(
        '保留天数', default=0, help_text='0 表示不参与自动清理')
    enabled = models.BooleanField('启用', default=True)
    note = models.CharField('说明', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '字段分级'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['resource', 'field'], name='s13_uniq_resource_field'),
        ]
        indexes = [models.Index(fields=['resource', 'enabled'])]

    def __str__(self):
        return '{}#{}'.format(self.resource, self.field)


DISCLOSURE_PENDING = 'pending'
DISCLOSURE_APPROVED = 'approved'
DISCLOSURE_REJECTED = 'rejected'
DISCLOSURE_EXECUTED = 'executed'
DISCLOSURE_EXPIRED = 'expired'
DISCLOSURE_STATUS = (
    (DISCLOSURE_PENDING, '待审批'),
    (DISCLOSURE_APPROVED, '已批准'),
    (DISCLOSURE_REJECTED, '已驳回'),
    (DISCLOSURE_EXECUTED, '已执行'),
    (DISCLOSURE_EXPIRED, '已过期'),
)


class DisclosureRequest(models.Model):
    resource = models.CharField('资源', max_length=64)
    fields = models.JSONField('字段列表', default=list, blank=True)
    purpose = models.CharField('用途', max_length=500)

    requester = models.ForeignKey(
        'r21_account.Account', verbose_name='申请人', on_delete=models.PROTECT,
        related_name='disclosure_requests')
    status = models.CharField('状态', max_length=16, choices=DISCLOSURE_STATUS,
                              default=DISCLOSURE_PENDING)

    approver = models.ForeignKey(
        'r21_account.Account', verbose_name='审批人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='disclosure_approved')
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    executed_by = models.ForeignKey(
        'r21_account.Account', verbose_name='执行人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='disclosure_executed')

    row_count = models.PositiveIntegerField('导出行数', default=0)
    output_digest = models.CharField('导出摘要', max_length=64, blank=True, default='')
    expires_at = models.DateTimeField('有效期至', null=True, blank=True)
    created_at = models.DateTimeField('申请时间', auto_now_add=True)

    class Meta:
        verbose_name = '数据披露申请'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['requester', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.resource, self.get_status_display())


class DisclosureLog(models.Model):
    """披露执行日志（append-only）。"""

    request_id = models.PositiveIntegerField('申请编号')
    resource = models.CharField('资源', max_length=64)
    fields = models.JSONField('字段', default=list, blank=True)
    actor_id_text = models.CharField('执行人', max_length=32, blank=True, default='')
    row_count = models.PositiveIntegerField('行数', default=0)
    digest = models.CharField('摘要', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '披露日志'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return '{} {}'.format(self.resource, self.created_at)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('披露日志为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('披露日志为 append-only，不允许删除')


class PrivacySample(models.Model):
    """用于验证保留期清理的合成样本。"""

    resource = models.CharField('资源', max_length=64, default='sample')
    payload = models.JSONField('数据', default=dict, blank=True)
    created_at = models.DateTimeField('产生时间', auto_now_add=True)

    class Meta:
        verbose_name = '保留期样本'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['resource', 'created_at'])]

    def __str__(self):
        return '{} {}'.format(self.resource, self.pk)
