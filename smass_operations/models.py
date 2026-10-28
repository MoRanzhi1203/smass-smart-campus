"""R9：可观测性、健康检查与告警（隔离模块）。

设计：
- ``RequestMetric`` 只存**非敏感**字段（路径模板、方法、状态码、耗时）；
  不存请求体、响应体、查询串、用户标识；
- ``AlertRule`` 是**配置**，``AlertEvent`` 是触发记录；不自动外发通知；
- readiness 检查数据库连通与迁移一致性，避免"进程活着但库不可用"。
"""
from django.db import models


class RequestMetric(models.Model):
    """请求级指标（采样记录）。"""

    method = models.CharField('方法', max_length=8)
    # 路径**模板**（如 /r5/years/），不含查询串与具体 ID
    route = models.CharField('路径', max_length=200)
    status_code = models.IntegerField('状态码')
    duration_ms = models.IntegerField('耗时毫秒')
    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = '请求指标'
        indexes = [
            models.Index(fields=['created_at', 'status_code']),
            models.Index(fields=['route', 'created_at']),
        ]


class AlertRule(models.Model):
    """告警规则（阈值配置）。"""

    METRIC_ERROR_RATE = 'error_rate'
    METRIC_LATENCY_P95 = 'latency_p95'
    METRIC_DB_ERRORS = 'db_errors'
    METRIC_CHOICES = (
        (METRIC_ERROR_RATE, '错误率'),
        (METRIC_LATENCY_P95, 'P95 延迟(ms)'),
        (METRIC_DB_ERRORS, '数据库错误数'),
    )

    SEVERITY_WARNING = 'warning'
    SEVERITY_CRITICAL = 'critical'
    SEVERITY_CHOICES = ((SEVERITY_WARNING, '警告'), (SEVERITY_CRITICAL, '严重'))

    code = models.CharField('规则编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=128)
    metric = models.CharField('指标', max_length=32, choices=METRIC_CHOICES)
    threshold = models.FloatField('阈值')
    window_seconds = models.IntegerField('窗口秒数', default=300)
    severity = models.CharField('级别', max_length=16, choices=SEVERITY_CHOICES,
                                default=SEVERITY_WARNING)
    is_enabled = models.BooleanField('启用', default=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警规则'
        indexes = [models.Index(fields=['is_enabled', 'metric'])]


class AlertEvent(models.Model):
    """告警触发记录（append-only）。"""

    rule = models.ForeignKey(
        AlertRule, verbose_name='规则', on_delete=models.CASCADE,
        related_name='events',
    )
    observed = models.FloatField('观测值')
    threshold = models.FloatField('阈值')
    severity = models.CharField('级别', max_length=16)
    detail = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = '告警事件'
        indexes = [models.Index(fields=['rule', 'created_at'])]


class ReadinessProbe(models.Model):
    """readiness 探针结果（便于排障）。"""

    name = models.CharField('检查项', max_length=64)
    ok = models.BooleanField('通过')
    detail = models.CharField('详情', max_length=255, blank=True, default='')
    duration_ms = models.IntegerField('耗时毫秒', default=0)
    checked_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = '就绪探针'
        indexes = [models.Index(fields=['name', 'checked_at'])]
