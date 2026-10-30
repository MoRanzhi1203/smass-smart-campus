"""S10：敏感操作再认证与双人审批（隔离模块）。

机制
----
1. **再认证（step-up）**：执行敏感操作前必须在有效期内（默认 5 分钟）
   重新通过密码或 TOTP；证明记录在 ``StepUpProof``；
2. **双人审批**：发起人生成工单，审批人必须**是另一账号**且具备审批权限；
   批准后由发起人（或管理员）执行，执行写 ``OperationLog``（append-only）；
3. **载荷摘要**：工单保存规范化载荷与 SHA-256，防止批准后被篡改；
4. **默认拒绝**：未再认证不能发起、不能自批、未批准不能执行、已执行不能重复执行。
"""
from __future__ import annotations

from django.db import models

#: 敏感操作注册表（操作码 → 说明与策略）
SENSITIVE_ACTIONS = {
    'export_sensitive': {'label': '导出敏感数据', 'dual': True, 'ttl': 300},
    'reset_other_password': {'label': '重置他人密码', 'dual': True, 'ttl': 300},
    'bulk_delete': {'label': '批量删除业务数据', 'dual': True, 'ttl': 300},
    'role_grant': {'label': '授予高权限角色', 'dual': True, 'ttl': 300},
}

METHOD_PASSWORD = 'password'
METHOD_TOTP = 'totp'
METHODS = (
    (METHOD_PASSWORD, '账号密码'),
    (METHOD_TOTP, '认证器 TOTP'),
)

APPROVAL_PENDING = 'pending'
APPROVAL_APPROVED = 'approved'
APPROVAL_REJECTED = 'rejected'
APPROVAL_EXECUTED = 'executed'
APPROVAL_EXPIRED = 'expired'
APPROVAL_STATUS = (
    (APPROVAL_PENDING, '待审批'),
    (APPROVAL_APPROVED, '已批准'),
    (APPROVAL_REJECTED, '已驳回'),
    (APPROVAL_EXECUTED, '已执行'),
    (APPROVAL_EXPIRED, '已过期'),
)


class StepUpProof(models.Model):
    """一次再认证成功的证明。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号', on_delete=models.CASCADE,
        related_name='stepup_proofs')
    action_code = models.CharField('操作码', max_length=64)
    method = models.CharField('方式', max_length=16, choices=METHODS,
                              default=METHOD_PASSWORD)
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    verified_at = models.DateTimeField('验证时间', auto_now_add=True)
    expires_at = models.DateTimeField('过期时间')

    class Meta:
        verbose_name = '再认证证明'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['account', 'action_code', 'expires_at']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.account_id, self.action_code, self.expires_at)


class DualApproval(models.Model):
    """双人审批工单。"""

    action_code = models.CharField('操作码', max_length=64)
    payload = models.JSONField('操作载荷', default=dict, blank=True)
    payload_digest = models.CharField('载荷摘要', max_length=64, blank=True, default='')
    reason = models.CharField('申请事由', max_length=500)

    requester = models.ForeignKey(
        'r21_account.Account', verbose_name='发起人', on_delete=models.PROTECT,
        related_name='stepup_approvals')
    status = models.CharField('状态', max_length=16, choices=APPROVAL_STATUS,
                              default=APPROVAL_PENDING)

    approver = models.ForeignKey(
        'r21_account.Account', verbose_name='审批人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='stepup_approved')
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    executed_by = models.ForeignKey(
        'r21_account.Account', verbose_name='执行人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='stepup_executed')

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '双人审批工单'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['requester', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.action_code, self.get_status_display())


class OperationLog(models.Model):
    """敏感操作执行日志（append-only）。"""

    action_code = models.CharField('操作码', max_length=64)
    payload_digest = models.CharField('载荷摘要', max_length=64, blank=True, default='')
    actor = models.ForeignKey(
        'r21_account.Account', verbose_name='执行人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='stepup_operations')
    actor_id_text = models.CharField('执行人标识', max_length=32, blank=True, default='')
    approval_id = models.PositiveIntegerField('审批工单', null=True, blank=True)
    result = models.CharField('结果', max_length=16, default='executed')
    detail = models.CharField('说明', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '敏感操作日志'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['action_code', '-created_at'])]

    def __str__(self):
        return '{} {}'.format(self.action_code, self.created_at)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('敏感操作日志为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('敏感操作日志为 append-only，不允许删除')
