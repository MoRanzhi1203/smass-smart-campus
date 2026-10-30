"""S11：策略感知与字段级授权（隔离模块）。

与既有 ``r21_account.authorization`` 的分工
------------------------------------------
- ``authorization`` 负责 RBAC / 组织域 / 对象级 / 静态字段白名单（代码内矩阵）；
- 本模块负责**可配置的字段策略**：读/写角色、业务状态条件、脱敏方式、决策审计。

策略判定顺序（默认拒绝）
------------------------
1. 无策略 / 策略停用 → 拒绝；
2. 账号角色与策略 ``read_roles`` / ``write_roles`` 无交集 → 拒绝；
3. 业务状态条件不满足 → 拒绝；
4. 允许 → 按 ``mask`` 脱敏后返回。
"""
from __future__ import annotations

from django.db import models

MASK_NONE = 'none'
MASK_PARTIAL = 'partial'
MASK_FULL = 'full'
MASK_CHOICES = (
    (MASK_NONE, '不脱敏'),
    (MASK_PARTIAL, '部分脱敏（保留首尾）'),
    (MASK_FULL, '完全遮挡'),
)


class FieldPolicy(models.Model):
    resource = models.CharField('资源', max_length=64)
    field = models.CharField('字段', max_length=64)

    read_roles = models.CharField('可读角色（逗号分隔）', max_length=200,
                                  blank=True, default='')
    write_roles = models.CharField('可写角色（逗号分隔）', max_length=200,
                                   blank=True, default='')
    mask = models.CharField('脱敏方式', max_length=16, choices=MASK_CHOICES,
                            default=MASK_NONE)
    #: 业务状态条件，如 {"status": ["active", "suspended"]}
    condition = models.JSONField('状态条件', default=dict, blank=True)
    enabled = models.BooleanField('启用', default=True)

    note = models.CharField('说明', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '字段策略'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['resource', 'field'], name='s11_uniq_resource_field'),
        ]
        indexes = [models.Index(fields=['resource', 'enabled'])]

    def __str__(self):
        return '{}#{}'.format(self.resource, self.field)


class PolicyDecisionLog(models.Model):
    """字段访问决策审计（append-only）。"""

    account_id_text = models.CharField('账号', max_length=32, blank=True, default='')
    resource = models.CharField('资源', max_length=64)
    field = models.CharField('字段', max_length=64)
    action = models.CharField('动作', max_length=16, default='read')
    allowed = models.BooleanField('允许', default=False)
    masked = models.BooleanField('是否脱敏', default=False)
    reason = models.CharField('原因码', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '字段决策日志'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return '{} {}'.format(self.resource, self.field)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('字段决策日志为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('字段决策日志为 append-only，不允许删除')
