"""R8：开放 API 与集成平台（隔离模块）。

安全设计（D08）：
- **服务账号**只存 token 的 SHA-256 摘要，不存明文；
- 默认 **无任何 scope**，必须显式授予（最小权限）；
- 请求不信任客户端自报的 role/account/scope，一律以服务账号的 scopes 判定；
- 写操作支持 ``Idempotency-Key``，重复提交返回首次结果；
- 每次调用写 ``ApiCallLog``（不含敏感数据）。
"""
import hashlib
import uuid

from django.db import models


def hash_token(raw):
    """token 摘要（不可逆），用于存储与比对。"""
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class ServiceAccount(models.Model):
    """服务账号（机器身份）。"""

    name = models.CharField('名称', max_length=64, unique=True)
    token_hash = models.CharField('令牌摘要', max_length=64, unique=True)
    # 默认空：不授予任何权限
    scopes = models.JSONField('权限范围', default=list, blank=True)
    is_active = models.BooleanField('启用', default=True)
    rate_limit_per_minute = models.IntegerField('每分钟限流', default=60)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '服务账号'
        indexes = [models.Index(fields=['is_active'])]

    def __str__(self):
        return self.name

    def has_scope(self, scope):
        return scope in (self.scopes or [])


class IdempotencyKey(models.Model):
    """幂等键：同一 key + 同一请求哈希只执行一次。"""

    key = models.CharField('幂等键', max_length=64, unique=True)
    account_name = models.CharField('服务账号', max_length=64, blank=True, default='')
    request_hash = models.CharField('请求哈希', max_length=32, blank=True, default='')
    response_json = models.JSONField('首次响应', default=dict, blank=True)
    status_code = models.IntegerField('首次状态码', default=200)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '幂等键'
        indexes = [models.Index(fields=['account_name', 'created_at'])]


class ApiCallLog(models.Model):
    """API 调用审计（不记录请求体与响应体）。"""

    account_name = models.CharField('服务账号', max_length=64, blank=True, default='')
    method = models.CharField('方法', max_length=8)
    path = models.CharField('路径', max_length=255)
    status_code = models.IntegerField('状态码')
    duration_ms = models.IntegerField('耗时毫秒', default=0)
    client_ip = models.CharField('来源 IP', max_length=45, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'API 调用日志'
        indexes = [models.Index(fields=['account_name', 'created_at'])]


class SyncJob(models.Model):
    """本地 mock 集成同步作业（不连接真实外部系统）。"""

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_PENDING, '待执行'),
        (STATUS_RUNNING, '执行中'),
        (STATUS_DONE, '完成'),
        (STATUS_FAILED, '失败'),
    )

    job_id = models.UUIDField('作业号', default=uuid.uuid4, unique=True, editable=False)
    connector = models.CharField('连接器', max_length=64, default='local_mock')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_PENDING)
    payload = models.JSONField('输入', default=dict, blank=True)
    result = models.JSONField('结果', default=dict, blank=True)
    replay_detected = models.BooleanField('检出重放', default=False)
    compensated = models.BooleanField('已补偿', default=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        verbose_name = '同步作业'
        indexes = [models.Index(fields=['connector', 'status'])]
