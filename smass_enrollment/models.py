"""R12：自动分班、转专业与学籍异动（隔离模块）。

设计约定
--------
1. **不改旧表结构**：学籍以 ``smass_organization.StudentRecord`` 为唯一档案，
   班级/专业复用 ``OrganizationUnit``（``unit_type='class'/'major'``）；
2. **先预览后执行**：分班先生成 ``PlacementBatch(status='preview')`` 与
   ``PlacementAssignment``，执行时才写 ``StudentRecord.unit``；
3. **可回滚**：执行时保留 ``from_unit``，回滚按批次恢复，并写档案变更历史；
4. **审批与生效分离**：转专业/学籍异动都是"提交 → 审批 → 生效"，
   审批人不得是提交人（与 S12 职责分离一致）；
5. **历史追加**：所有档案变化写 ``StudentRecordChange``（append-only）。
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q

# ---------------------------------------------------------------------------
# 分班
# ---------------------------------------------------------------------------
PLACEMENT_PREVIEW = 'preview'
PLACEMENT_APPLIED = 'applied'
PLACEMENT_ROLLED_BACK = 'rolled_back'
PLACEMENT_STATUS = (
    (PLACEMENT_PREVIEW, '预览'),
    (PLACEMENT_APPLIED, '已执行'),
    (PLACEMENT_ROLLED_BACK, '已回滚'),
)

STRATEGY_BALANCED = 'balanced'
STRATEGY_ROUND_ROBIN = 'round_robin'
PLACEMENT_STRATEGIES = (
    (STRATEGY_BALANCED, '均衡分配（按维度轮流打散）'),
    (STRATEGY_ROUND_ROBIN, '顺序轮转（按学号依次入班）'),
)

ASSIGNMENT_PLANNED = 'planned'
ASSIGNMENT_APPLIED = 'applied'
ASSIGNMENT_ROLLED_BACK = 'rolled_back'
ASSIGNMENT_STATUS = (
    (ASSIGNMENT_PLANNED, '待执行'),
    (ASSIGNMENT_APPLIED, '已执行'),
    (ASSIGNMENT_ROLLED_BACK, '已回滚'),
)


class PlacementRule(models.Model):
    """分班规则（B 类可配置：容量、策略、均衡维度）。"""

    name = models.CharField('规则名称', max_length=64)
    major = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='专业',
        on_delete=models.PROTECT, related_name='placement_rules',
    )
    grade_label = models.CharField('年级标签', max_length=32, blank=True, default='')
    capacity_per_class = models.PositiveIntegerField(
        '每班容量', default=0, help_text='0 表示不限容量')
    strategy = models.CharField(
        '分配策略', max_length=16, choices=PLACEMENT_STRATEGIES,
        default=STRATEGY_BALANCED)
    balance_keys = models.JSONField(
        '均衡维度', default=list, blank=True,
        help_text="依次均衡的档案字段，如 ['sex', 'source']；值来自 StudentRecord.extra")
    is_active = models.BooleanField('启用', default=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '分班规则'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['major', 'is_active'])]

    def __str__(self):
        return '{}（{}）'.format(self.name, self.major.name)


class PlacementBatch(models.Model):
    """一次分班批次：预览 → 执行 → 可回滚。"""

    rule = models.ForeignKey(
        PlacementRule, verbose_name='规则',
        on_delete=models.PROTECT, related_name='batches')
    status = models.CharField('状态', max_length=16, choices=PLACEMENT_STATUS,
                              default=PLACEMENT_PREVIEW)
    actor_id = models.CharField('操作者', max_length=32, blank=True, default='')
    stats = models.JSONField('统计', default=dict, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    applied_at = models.DateTimeField('执行时间', null=True, blank=True)
    rolled_back_at = models.DateTimeField('回滚时间', null=True, blank=True)

    class Meta:
        verbose_name = '分班批次'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['rule', 'status']),
        ]

    def __str__(self):
        return '批次 {} {}'.format(self.pk, self.get_status_display())


class PlacementAssignment(models.Model):
    """分班结果行：预览阶段即为计划，执行后写档案。"""

    batch = models.ForeignKey(
        PlacementBatch, verbose_name='批次',
        on_delete=models.CASCADE, related_name='assignments')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='placement_assignments')
    from_unit = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='原组织',
        null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    to_unit = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='目标班级',
        on_delete=models.PROTECT, related_name='+')
    status = models.CharField('状态', max_length=16, choices=ASSIGNMENT_STATUS,
                              default=ASSIGNMENT_PLANNED)

    class Meta:
        verbose_name = '分班结果'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'record'], name='r12_uniq_batch_record'),
        ]
        indexes = [models.Index(fields=['record', 'status'])]

    def __str__(self):
        return '{} -> {}'.format(self.record.student_no, self.to_unit.code)


# ---------------------------------------------------------------------------
# 转专业
# ---------------------------------------------------------------------------
TRANSFER_SUBMITTED = 'submitted'
TRANSFER_APPROVED = 'approved'
TRANSFER_REJECTED = 'rejected'
TRANSFER_EFFECTIVE = 'effective'
TRANSFER_CANCELLED = 'cancelled'
TRANSFER_STATUS = (
    (TRANSFER_SUBMITTED, '待审批'),
    (TRANSFER_APPROVED, '已批准（待生效）'),
    (TRANSFER_REJECTED, '已驳回'),
    (TRANSFER_EFFECTIVE, '已生效'),
    (TRANSFER_CANCELLED, '已撤销'),
)


class MajorTransferRequest(models.Model):
    """转专业申请：提交 → 审批 → 生效（编入目标班级）。"""

    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='transfer_requests')
    from_unit = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='当前组织',
        null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    to_major = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='目标专业',
        on_delete=models.PROTECT, related_name='+')
    target_class = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='目标班级',
        null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    reason = models.CharField('申请理由', max_length=500, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=TRANSFER_STATUS,
                              default=TRANSFER_SUBMITTED)
    submitted_by = models.CharField('提交人', max_length=32, blank=True, default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    effective_at = models.DateTimeField('生效时间', null=True, blank=True)

    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '转专业申请'
        verbose_name_plural = verbose_name
        constraints = [
            # 同一档案同时只能有一条进行中的申请（防重复提交/并发双批）
            models.UniqueConstraint(
                fields=['record'],
                condition=Q(status__in=[TRANSFER_SUBMITTED, TRANSFER_APPROVED]),
                name='r12_uniq_active_transfer',
            ),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '转专业 {} {}'.format(self.record.student_no, self.get_status_display())


# ---------------------------------------------------------------------------
# 学籍异动
# ---------------------------------------------------------------------------
CHANGE_SUSPEND = 'suspend'
CHANGE_RESUME = 'resume'
CHANGE_WITHDRAW = 'withdraw'
CHANGE_GRADUATE = 'graduate'
CHANGE_TRANSFER_OUT = 'transfer_out'
CHANGE_TYPES = (
    (CHANGE_SUSPEND, '休学'),
    (CHANGE_RESUME, '复学'),
    (CHANGE_WITHDRAW, '退学'),
    (CHANGE_GRADUATE, '毕业'),
    (CHANGE_TRANSFER_OUT, '转出'),
)

CHANGE_SUBMITTED = 'submitted'
CHANGE_APPROVED = 'approved'
CHANGE_REJECTED = 'rejected'
CHANGE_EFFECTIVE = 'effective'
CHANGE_CANCELLED = 'cancelled'
CHANGE_STATUS = (
    (CHANGE_SUBMITTED, '待审批'),
    (CHANGE_APPROVED, '已批准（待生效）'),
    (CHANGE_REJECTED, '已驳回'),
    (CHANGE_EFFECTIVE, '已生效'),
    (CHANGE_CANCELLED, '已撤销'),
)


class StudentStatusChange(models.Model):
    """学籍异动：休学/复学/退学/毕业/转出。"""

    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='status_changes')
    change_type = models.CharField('异动类型', max_length=16, choices=CHANGE_TYPES)
    from_status = models.CharField('原学籍状态', max_length=16, blank=True, default='')
    to_status = models.CharField('目标学籍状态', max_length=16, blank=True, default='')
    effective_date = models.DateField('生效日期', null=True, blank=True)
    reason = models.CharField('原因', max_length=500, blank=True, default='')

    status = models.CharField('状态', max_length=16, choices=CHANGE_STATUS,
                              default=CHANGE_SUBMITTED)
    submitted_by = models.CharField('提交人', max_length=32, blank=True, default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    effective_at = models.DateTimeField('生效时间', null=True, blank=True)

    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '学籍异动'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['record'],
                condition=Q(status__in=[CHANGE_SUBMITTED, CHANGE_APPROVED]),
                name='r12_uniq_active_status_change',
            ),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.record.student_no, self.get_change_type_display())
