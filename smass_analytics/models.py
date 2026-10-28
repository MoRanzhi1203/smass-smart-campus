"""R7：指标注册、看板、报表（定义与计算分离，D07）。

原则：
- 指标必须有**版本、数据源、口径、权限**，未校验不启用；
- 计算前先应用 scope 过滤（复用 R4/R5/R6 的服务），避免聚合泄漏；
- 每次计算结果记录 ``query_hash`` 与 ``scope_hash``，可复现、可对账；
- 不预设学校 KPI（如挂科率、质量分），这些属政策指标，需 BD-07。
"""
import hashlib
import json

from django.db import models


def hash_payload(payload):
    """确定性哈希（排序键、紧凑分隔符）。"""
    text = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]


class MetricDefinition(models.Model):
    """指标定义（注册表）。"""

    DATA_SOURCES = (
        ('organization', '组织'),
        ('student', '学生档案'),
        ('academic', '教学'),
        ('workflow', '工作流'),
    )

    code = models.CharField('指标编码', max_length=64, unique=True)
    name = models.CharField('指标名称', max_length=128)
    description = models.CharField('口径说明', max_length=255, blank=True, default='')
    data_source = models.CharField('数据源', max_length=32, choices=DATA_SOURCES)
    # 计算口径：由代码中的 compute 函数按 code 分派，此处记录**声明**以便审计
    definition = models.JSONField('定义', default=dict, blank=True)
    period = models.CharField('统计周期', max_length=32, default='realtime')
    precision = models.IntegerField('小数位', default=0)
    owner = models.CharField('责任人', max_length=32, blank=True, default='')
    permission_roles = models.JSONField('可见角色', default=list, blank=True)

    version = models.IntegerField('版本号', default=1)
    is_enabled = models.BooleanField('已启用', default=False)
    validated_at = models.DateTimeField('校验时间', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '指标定义'
        indexes = [models.Index(fields=['data_source', 'is_enabled'])]

    def __str__(self):
        return '{} v{}'.format(self.code, self.version)


class MetricSnapshot(models.Model):
    """指标计算结果快照（可复现、可对账）。"""

    metric = models.ForeignKey(
        MetricDefinition, verbose_name='指标', on_delete=models.CASCADE,
        related_name='snapshots',
    )
    metric_version = models.IntegerField('指标版本')
    value = models.DecimalField('数值', max_digits=18, decimal_places=4)
    scope_hash = models.CharField('范围哈希', max_length=32, blank=True, default='')
    query_hash = models.CharField('查询哈希', max_length=32, blank=True, default='')
    computed_by = models.CharField('计算者', max_length=32, blank=True, default='')
    computed_at = models.DateTimeField('计算时间', auto_now_add=True)

    class Meta:
        verbose_name = '指标快照'
        indexes = [
            models.Index(fields=['metric', 'computed_at']),
            models.Index(fields=['query_hash']),
        ]


class ReportDefinition(models.Model):
    """报表定义（组合多个指标）。"""

    code = models.CharField('报表编码', max_length=64, unique=True)
    name = models.CharField('报表名称', max_length=128)
    metrics = models.ManyToManyField(
        MetricDefinition, verbose_name='指标', related_name='reports', blank=True
    )
    permission_roles = models.JSONField('可见角色', default=list, blank=True)
    is_enabled = models.BooleanField('已启用', default=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '报表定义'


class ReportRun(models.Model):
    """报表运行记录。"""

    STATUS_OK = 'ok'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = ((STATUS_OK, '成功'), (STATUS_FAILED, '失败'))

    report = models.ForeignKey(
        ReportDefinition, verbose_name='报表', on_delete=models.CASCADE,
        related_name='runs',
    )
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES)
    row_count = models.IntegerField('行数', default=0)
    query_hash = models.CharField('查询哈希', max_length=32, blank=True, default='')
    scope_hash = models.CharField('范围哈希', max_length=32, blank=True, default='')
    rows = models.JSONField('结果行', default=list, blank=True)
    ran_by = models.CharField('运行者', max_length=32, blank=True, default='')
    ran_at = models.DateTimeField('运行时间', auto_now_add=True)

    class Meta:
        verbose_name = '报表运行'
        indexes = [models.Index(fields=['report', 'ran_at'])]


class DataQualityIssue(models.Model):
    """数据质量告警（例如口径不匹配、聚合样本过小）。"""

    SEVERITY_INFO = 'info'
    SEVERITY_WARN = 'warning'
    SEVERITY_CHOICES = ((SEVERITY_INFO, '提示'), (SEVERITY_WARN, '警告'))

    code = models.CharField('问题码', max_length=32)
    metric = models.ForeignKey(
        MetricDefinition, verbose_name='指标', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='issues',
    )
    message = models.CharField('说明', max_length=255)
    severity = models.CharField('级别', max_length=16, choices=SEVERITY_CHOICES,
                                default=SEVERITY_INFO)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '数据质量问题'
        indexes = [models.Index(fields=['metric', 'created_at'])]
