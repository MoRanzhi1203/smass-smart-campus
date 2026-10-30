"""S16：追加式审计与安全告警（隔离模块）。

设计要点
--------
1. **哈希链**：每条事件包含 ``prev_hash`` 与 ``hash = SHA256(prev_hash + 规范化字段)``，
   任意一条被篡改都会让后续链校验失败；
2. **append-only**：模型 ``save()/delete()`` 对已存在记录直接抛错；
3. **告警**：按窗口统计 ``denied`` 事件，超过阈值生成 ``SecurityAlert``（同主体同类型
   在窗口内只开一条），用于特权滥用/越权探测；
4. **默认拒绝**：事件与告警只对审计管理员可见，普通账号只看自己的事件。
"""
from __future__ import annotations

from django.db import models

RESULT_SUCCESS = 'success'
RESULT_DENIED = 'denied'
RESULT_ERROR = 'error'
RESULTS = (
    (RESULT_SUCCESS, '成功'),
    (RESULT_DENIED, '拒绝'),
    (RESULT_ERROR, '错误'),
)

SEVERITY_LOW = 'low'
SEVERITY_MEDIUM = 'medium'
SEVERITY_HIGH = 'high'
SEVERITIES = (
    (SEVERITY_LOW, '低'),
    (SEVERITY_MEDIUM, '中'),
    (SEVERITY_HIGH, '高'),
)

ALERT_DENIED_BURST = 'denied_burst'
ALERT_PRIVILEGE = 'privilege_change'
ALERT_CONFLICT = 'conflict'
ALERT_TYPES = (
    (ALERT_DENIED_BURST, '越权/拒绝突增'),
    (ALERT_PRIVILEGE, '特权变更'),
    (ALERT_CONFLICT, '身份/数据冲突'),
)

ALERT_OPEN = 'open'
ALERT_ACK = 'acknowledged'
ALERT_STATUS = (
    (ALERT_OPEN, '待处理'),
    (ALERT_ACK, '已确认'),
)


class AuditEvent(models.Model):
    event_no = models.CharField('事件号', max_length=64, unique=True)
    actor_id = models.CharField('主体', max_length=32, blank=True, default='',
                                db_index=True)
    actor_role = models.CharField('角色', max_length=32, blank=True, default='')
    action = models.CharField('动作', max_length=64)
    resource = models.CharField('资源', max_length=64, blank=True, default='')
    resource_id = models.CharField('资源标识', max_length=64, blank=True, default='')
    result = models.CharField('结果', max_length=16, choices=RESULTS,
                              default=RESULT_SUCCESS)
    reason = models.CharField('原因码', max_length=120, blank=True, default='')
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    meta = models.JSONField('附加信息', default=dict, blank=True)

    prev_hash = models.CharField('前一条哈希', max_length=64, blank=True, default='')
    hash = models.CharField('本条哈希', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '审计事件'
        verbose_name_plural = verbose_name
        ordering = ['id']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['actor_id', 'result']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.event_no, self.action, self.result)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('审计事件为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('审计事件为 append-only，不允许删除')


class SecurityAlert(models.Model):
    alert_type = models.CharField('类型', max_length=24, choices=ALERT_TYPES)
    severity = models.CharField('严重度', max_length=16, choices=SEVERITIES,
                                default=SEVERITY_MEDIUM)
    subject = models.CharField('主体', max_length=64, blank=True, default='')
    detail = models.JSONField('详情', default=dict, blank=True)
    status = models.CharField('状态', max_length=16, choices=ALERT_STATUS,
                              default=ALERT_OPEN)
    acknowledged_by = models.CharField('确认人', max_length=32, blank=True, default='')
    acknowledged_at = models.DateTimeField('确认时间', null=True, blank=True)
    created_at = models.DateTimeField('产生时间', auto_now_add=True)

    class Meta:
        verbose_name = '安全告警'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['alert_type', 'subject', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.get_alert_type_display(), self.subject)
