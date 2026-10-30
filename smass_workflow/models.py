"""R6：可配置审批工作流（版本化定义 + 实例 + 事件）。

设计（D06）：
- ``WorkflowDefinition`` 是"流程"身份，``WorkflowVersion`` 是**不可变快照**；
- 已启动的 ``WorkflowInstance`` 固定绑定创建时的 version，定义变更不影响运行中实例；
- 状态转移许可由 version 内的 ``WorkflowTransition`` 决定，**代码不硬编码学校政策**；
- 演示流程默认 ``is_active=False``，不自动成为正式规则。
"""
import uuid

from django.db import models
from django.db.models import Q


def _uuid_str():
    return str(uuid.uuid4())


class WorkflowDefinition(models.Model):
    """流程定义（身份）。"""

    code = models.CharField('流程编码', max_length=64, unique=True)
    name = models.CharField('流程名称', max_length=128)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    # 默认不启用：演示/新建流程需要显式发布才会生效（D05）
    is_active = models.BooleanField('已启用', default=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '流程定义'
        indexes = [models.Index(fields=['code', 'is_active'])]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


class WorkflowVersion(models.Model):
    """流程版本（不可变快照）。"""

    STATUS_DRAFT = 'draft'
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = (
        (STATUS_DRAFT, '草稿'),
        (STATUS_ACTIVE, '启用'),
        (STATUS_ARCHIVED, '归档'),
    )

    definition = models.ForeignKey(
        WorkflowDefinition, verbose_name='流程', on_delete=models.CASCADE,
        related_name='versions',
    )
    version = models.IntegerField('版本号')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)

    class Meta:
        verbose_name = '流程版本'
        constraints = [
            models.UniqueConstraint(
                fields=['definition', 'version'], name='r6_uniq_version'
            ),
        ]
        indexes = [models.Index(fields=['definition', 'status'])]

    def __str__(self):
        return '{} v{}'.format(self.definition.code, self.version)


class WorkflowNode(models.Model):
    """流程节点。"""

    NODE_START = 'start'
    NODE_APPROVAL = 'approval'
    NODE_END = 'end'
    NODE_CHOICES = (
        (NODE_START, '开始'),
        (NODE_APPROVAL, '审批'),
        (NODE_END, '结束'),
    )

    version = models.ForeignKey(
        WorkflowVersion, verbose_name='版本', on_delete=models.CASCADE,
        related_name='nodes',
    )
    code = models.CharField('节点编码', max_length=64)
    name = models.CharField('节点名称', max_length=128)
    node_type = models.CharField('类型', max_length=16, choices=NODE_CHOICES)
    order = models.IntegerField('顺序', default=0)

    class Meta:
        verbose_name = '流程节点'
        constraints = [
            models.UniqueConstraint(
                fields=['version', 'code'], name='r6_uniq_node_code'
            ),
        ]
        indexes = [models.Index(fields=['version', 'order'])]

    def __str__(self):
        return '{}:{}'.format(self.version_id, self.code)


class WorkflowTransition(models.Model):
    """节点之间的允许转移（由配置决定，不硬编码政策）。"""

    version = models.ForeignKey(
        WorkflowVersion, verbose_name='版本', on_delete=models.CASCADE,
        related_name='transitions',
    )
    from_node = models.ForeignKey(
        WorkflowNode, verbose_name='源节点', on_delete=models.CASCADE,
        related_name='outgoing',
    )
    to_node = models.ForeignKey(
        WorkflowNode, verbose_name='目标节点', on_delete=models.CASCADE,
        related_name='incoming',
    )
    action = models.CharField('动作', max_length=32)

    class Meta:
        verbose_name = '流程转移'
        constraints = [
            models.UniqueConstraint(
                fields=['version', 'from_node', 'action'], name='r6_uniq_transition'
            ),
        ]
        indexes = [models.Index(fields=['version', 'action'])]


class WorkflowInstance(models.Model):
    """流程实例（绑定创建时的版本，永不被后续定义变更影响）。"""

    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'
    STATUS_CHOICES = (
        (STATUS_DRAFT, '草稿'),
        (STATUS_PENDING, '审批中'),
        (STATUS_APPROVED, '已通过'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_WITHDRAWN, '已撤回'),
    )

    version = models.ForeignKey(
        WorkflowVersion, verbose_name='版本', on_delete=models.PROTECT,
        related_name='instances',
    )
    subject_type = models.CharField('业务类型', max_length=64)
    subject_id = models.CharField('业务标识', max_length=64)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT)
    current_node = models.ForeignKey(
        WorkflowNode, verbose_name='当前节点', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='current_instances',
    )
    created_by = models.CharField('发起人', max_length=32, blank=True, default='')
    version_no = models.IntegerField('乐观锁版本', default=1)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '流程实例'
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['subject_type', 'subject_id']),
        ]


class WorkflowEvent(models.Model):
    """实例事件（append-only，审批历史唯一来源）。"""

    instance = models.ForeignKey(
        WorkflowInstance, verbose_name='实例', on_delete=models.CASCADE,
        related_name='events',
    )
    action = models.CharField('动作', max_length=32)
    from_status = models.CharField('原状态', max_length=16, blank=True, default='')
    to_status = models.CharField('新状态', max_length=16, blank=True, default='')
    from_node = models.CharField('原节点', max_length=64, blank=True, default='')
    to_node = models.CharField('新节点', max_length=64, blank=True, default='')
    actor = models.CharField('操作者', max_length=32, blank=True, default='')
    reason = models.CharField('原因', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = '流程事件'
        indexes = [models.Index(fields=['instance', 'created_at'])]

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if not self._state.adding:
            raise ValidationError('审批事件为追加式记录，不允许修改')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError('审批事件为追加式记录，不允许删除')


class ApprovalTask(models.Model):
    """待办任务。"""

    STATUS_OPEN = 'open'
    STATUS_DONE = 'done'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_OPEN, '待处理'),
        (STATUS_DONE, '已处理'),
        (STATUS_CANCELLED, '已取消'),
    )

    instance = models.ForeignKey(
        WorkflowInstance, verbose_name='实例', on_delete=models.CASCADE,
        related_name='tasks',
    )
    node = models.ForeignKey(
        WorkflowNode, verbose_name='节点', on_delete=models.CASCADE,
        related_name='tasks',
    )
    assignee = models.CharField('处理人', max_length=32, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)
    idempotency_key = models.CharField('幂等键', max_length=64, blank=True, default='')

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        verbose_name = '审批任务'
        # H2：MySQL 不支持条件唯一索引（models.W036），原
        # UniqueConstraint(condition=Q(status='open')) 在数据库层从未被创建。
        # 真实约束由迁移 0003_open_task_unique 的两个生成列
        # （open_instance_id / open_node_id）+ 唯一索引 uq_r6_open_task 提供：
        #   open 行    -> 生成列 = instance_id / node_id
        #   其他状态   -> NULL（唯一索引中 NULL 互不相等）
        constraints = []
        indexes = [models.Index(fields=['assignee', 'status'])]


class Notification(models.Model):
    """站内通知（不外发）。"""

    LEVEL_INFO = 'info'
    LEVEL_WARNING = 'warning'
    LEVEL_CHOICES = ((LEVEL_INFO, '提示'), (LEVEL_WARNING, '警告'))

    recipient = models.CharField('接收人', max_length=32)
    title = models.CharField('标题', max_length=128)
    body = models.CharField('内容', max_length=512, blank=True, default='')
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES,
                             default=LEVEL_INFO)
    # 幂等键：调用方不传时用 UUID 兜底，保证永不为空
    # （MySQL 不支持条件唯一索引，因此这里用普通唯一约束）
    event_key = models.CharField('事件键（幂等）', max_length=96, blank=True,
                                 default=_uuid_str)
    is_read = models.BooleanField('已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '站内通知'
        constraints = [
            models.UniqueConstraint(
                fields=['recipient', 'event_key'], name='r6_uniq_notification_event'
            ),
        ]
        indexes = [models.Index(fields=['recipient', 'is_read'])]
