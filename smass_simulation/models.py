"""V2.1 仿真批次：记录生成批次、阶段进度与对象归属，支撑幂等/断点/清理。"""
from __future__ import annotations

from django.db import models


class SimulationBatch(models.Model):
    STATUS_CREATED = 'created'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_CREATED, '已创建'),
        (STATUS_RUNNING, '生成中'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_FAILED, '失败'),
    )

    code = models.CharField('批次编码', max_length=64, unique=True)
    profile = models.CharField('档位', max_length=16, default='medium')
    seed = models.BigIntegerField('随机种子', default=0)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_CREATED)
    stage_done = models.JSONField('已完成阶段', default=dict, blank=True)
    counts = models.JSONField('规模统计', default=dict, blank=True)
    duration_ms = models.IntegerField('耗时毫秒', default=0)
    note = models.CharField('备注', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '仿真批次'
        indexes = [models.Index(fields=['profile', 'status'])]

    def __str__(self):
        return '{} ({})'.format(self.code, self.profile)


class SimulationObject(models.Model):
    batch = models.ForeignKey(SimulationBatch, verbose_name='批次',
                              on_delete=models.CASCADE,
                              related_name='objects')
    model_label = models.CharField('模型', max_length=64)
    object_pk = models.CharField('对象主键', max_length=64)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '仿真对象'
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'model_label', 'object_pk'],
                name='sim_uniq_batch_model_pk'),
        ]
        indexes = [models.Index(fields=['batch', 'model_label'])]

    def __str__(self):
        return '{}#{}'.format(self.model_label, self.object_pk)
