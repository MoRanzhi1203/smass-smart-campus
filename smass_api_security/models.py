"""S15：API 安全（scope、幂等、令牌吊销、限流、重放防护）。

机制
----
1. **令牌**：``Bearer <token>``，库中只存 SHA-256；支持过期与吊销；
2. **scope**：令牌携带 scope 集合，端点声明所需 scope，默认拒绝；
3. **限流**：按令牌 + 固定窗口计数（默认 60 秒），超限返回 429；
4. **幂等**：``Idempotency-Key`` 命中则返回缓存响应；同键不同请求体返回 409；
5. **重放防护**：``X-Timestamp``（±300 秒）+ ``X-Nonce``（一次性，唯一约束）；
6. **审计**：每次请求写 ``ApiRequestLog``（append-only）。
"""
from __future__ import annotations

from django.db import models

CLIENT_ACTIVE = 'active'
CLIENT_DISABLED = 'disabled'


class ApiClient(models.Model):
    name = models.CharField('名称', max_length=100)
    client_id = models.CharField('客户端 ID', max_length=64, unique=True)
    status = models.CharField('状态', max_length=16, default=CLIENT_ACTIVE)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'API 客户端'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '{} {}'.format(self.client_id, self.name)


class ApiToken(models.Model):
    client = models.ForeignKey(
        ApiClient, verbose_name='客户端', on_delete=models.CASCADE,
        related_name='tokens')
    token_hash = models.CharField('令牌哈希', max_length=64, unique=True)
    scopes = models.CharField('scope（逗号分隔）', max_length=300, blank=True, default='')
    issued_at = models.DateTimeField('签发时间', auto_now_add=True)
    expires_at = models.DateTimeField('过期时间')
    revoked_at = models.DateTimeField('吊销时间', null=True, blank=True)
    last_used_at = models.DateTimeField('最近使用', null=True, blank=True)

    class Meta:
        verbose_name = 'API 令牌'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['client', 'revoked_at'])]

    def __str__(self):
        return '{} token={}'.format(self.client_id if self.client_id else '-',
                                    self.token_hash[:8])


class IdempotencyKey(models.Model):
    token = models.ForeignKey(
        ApiToken, verbose_name='令牌', on_delete=models.CASCADE,
        related_name='idempotency_keys')
    key = models.CharField('幂等键', max_length=128)
    request_digest = models.CharField('请求摘要', max_length=64)
    response_status = models.PositiveIntegerField('响应码', default=200)
    response_body = models.TextField('响应体', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '幂等键'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['token', 'key'], name='s15_uniq_token_key'),
        ]

    def __str__(self):
        return '{} {}'.format(self.token_id, self.key[:12])


class RateLimitBucket(models.Model):
    token = models.ForeignKey(
        ApiToken, verbose_name='令牌', on_delete=models.CASCADE,
        related_name='rate_buckets')
    window_start = models.DateTimeField('窗口起点')
    count = models.PositiveIntegerField('计数', default=0)

    class Meta:
        verbose_name = '限流窗口'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['token', 'window_start'], name='s15_uniq_token_window'),
        ]

    def __str__(self):
        return '{} {}'.format(self.token_id, self.window_start)


class Nonce(models.Model):
    """一次性随机数（重放防护）。"""

    token = models.ForeignKey(
        ApiToken, verbose_name='令牌', on_delete=models.CASCADE,
        related_name='nonces')
    nonce = models.CharField('随机数', max_length=64)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '请求随机数'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['token', 'nonce'], name='s15_uniq_token_nonce'),
        ]
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return '{} {}'.format(self.token_id, self.nonce[:12])


class ApiRequestLog(models.Model):
    """API 请求审计（append-only）。"""

    token_hash_prefix = models.CharField('令牌前缀', max_length=16, blank=True,
                                         default='')
    method = models.CharField('方法', max_length=8)
    path = models.CharField('路径', max_length=200)
    status = models.PositiveIntegerField('响应码', default=200)
    reason = models.CharField('原因码', max_length=64, blank=True, default='')
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = 'API 请求日志'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return '{} {} {}'.format(self.method, self.path, self.status)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('API 请求日志为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('API 请求日志为 append-only，不允许删除')
