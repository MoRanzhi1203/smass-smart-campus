"""S09：特权角色多因素认证（TOTP + 恢复码）。

设计约定
--------
1. **纯标准库实现 TOTP**（RFC 6238，HMAC-SHA1 / 30 秒 / 6 位），不引入三方依赖；
2. 特权角色（默认 ``system_admin``/``college_admin``）**必须**启用 MFA，
   未启用时中间件强制跳转 setup；
3. 已启用后每次登录需二次验证，验证状态写入 session 并带过期时间；
4. 恢复码只存 SHA-256，明文仅在生成时展示一次；
5. ``MFA_ENABLED``/``MFA_REQUIRED_ROLES`` 可配置，关闭时不改变既有登录行为；
6. 生产环境 secret 应加密存储（当前为合成/开发基线，见文档"已知边界"）。
"""
from __future__ import annotations

from django.db import models

STATUS_PENDING = 'pending'
STATUS_ACTIVE = 'active'
STATUS_DISABLED = 'disabled'
DEVICE_STATUS = (
    (STATUS_PENDING, '待确认'),
    (STATUS_ACTIVE, '已启用'),
    (STATUS_DISABLED, '已停用'),
)


class MfaDevice(models.Model):
    account = models.OneToOneField(
        'r21_account.Account', verbose_name='账号', on_delete=models.CASCADE,
        related_name='mfa_device')
    secret = models.CharField('TOTP 密钥（Base32）', max_length=64)
    status = models.CharField('状态', max_length=16, choices=DEVICE_STATUS,
                              default=STATUS_PENDING)
    failed_attempts = models.PositiveIntegerField('连续失败次数', default=0)
    last_used_at = models.DateTimeField('最近使用', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    confirmed_at = models.DateTimeField('确认时间', null=True, blank=True)

    class Meta:
        verbose_name = 'MFA 设备'
        verbose_name_plural = verbose_name

    def __str__(self):
        return 'MFA {} {}'.format(self.account_id, self.status)


class RecoveryCode(models.Model):
    """一次性恢复码（只存哈希）。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号', on_delete=models.CASCADE,
        related_name='mfa_recovery_codes')
    code_hash = models.CharField('哈希', max_length=64)
    used_at = models.DateTimeField('使用时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '恢复码'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['account', 'used_at']),
            models.Index(fields=['code_hash']),
        ]

    def __str__(self):
        return 'RecoveryCode {} {}'.format(self.account_id, self.used_at)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('恢复码为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('恢复码为 append-only，不允许删除')
