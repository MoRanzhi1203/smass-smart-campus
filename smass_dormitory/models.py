"""V2.1 宿舍业务域。

楼栋与房间复用 ``smass_facilities.Building/Room`` 作为唯一权威，
本模块只补充宿舍属性（宿舍区、容量、床位、住宿关系、调宿/退宿、报修、巡查、宿管范围）。

MySQL 无部分唯一索引：用 ``active_slot``（活跃=1，历史=NULL）+ 普通唯一约束
实现“同一学生/床位同时只有一条活跃记录”。
"""
from __future__ import annotations

from django.db import models

from smass_organization.models import StudentRecord


class DormZone(models.Model):
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = ((STATUS_OPEN, '启用'), (STATUS_CLOSED, '停用'))

    code = models.CharField('宿舍区编码', max_length=32, unique=True)
    name = models.CharField('名称', max_length=64)
    campus = models.CharField('校区', max_length=64, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '宿舍区'
        ordering = ['code']

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


class DormBuilding(models.Model):
    GENDER_MIXED = 'mixed'
    GENDER_MALE = 'male'
    GENDER_FEMALE = 'female'
    GENDER_CHOICES = (
        (GENDER_MIXED, '混合'),
        (GENDER_MALE, '男生楼'),
        (GENDER_FEMALE, '女生楼'),
    )
    STATUS_OPEN = 'open'
    STATUS_MAINTENANCE = 'maintenance'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = (
        (STATUS_OPEN, '正常'),
        (STATUS_MAINTENANCE, '维护中'),
        (STATUS_CLOSED, '停用'),
    )

    building = models.OneToOneField(
        'smass_facilities.Building', verbose_name='楼宇',
        on_delete=models.PROTECT, related_name='dorm_building')
    zone = models.ForeignKey(DormZone, verbose_name='宿舍区',
                             on_delete=models.PROTECT,
                             related_name='buildings')
    gender_policy = models.CharField('住宿区适配', max_length=16,
                                     choices=GENDER_CHOICES,
                                     default=GENDER_MIXED)
    floors = models.SmallIntegerField('楼层数', default=6)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '宿舍楼'
        ordering = ['building__code']

    def __str__(self):
        return str(self.building)


class DormRoom(models.Model):
    ROOM_4 = 4
    ROOM_6 = 6
    ROOM_8 = 8
    ROOM_TYPES = ((ROOM_4, '四人间'), (ROOM_6, '六人间'), (ROOM_8, '八人间'))
    STATUS_OPEN = 'open'
    STATUS_DISABLED = 'disabled'
    STATUS_MAINTENANCE = 'maintenance'
    STATUS_CHOICES = (
        (STATUS_OPEN, '可用'),
        (STATUS_DISABLED, '停用'),
        (STATUS_MAINTENANCE, '维护中'),
    )

    room = models.OneToOneField(
        'smass_facilities.Room', verbose_name='房间',
        on_delete=models.PROTECT, related_name='dorm_room')
    building = models.ForeignKey(DormBuilding, verbose_name='宿舍楼',
                                 on_delete=models.CASCADE,
                                 related_name='rooms')
    capacity = models.SmallIntegerField('容量', default=ROOM_4,
                                        choices=ROOM_TYPES)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '寝室'
        ordering = ['building__building__code', 'room__code']

    def __str__(self):
        return '{} {}'.format(self.building, self.room)


class Bed(models.Model):
    STATUS_FREE = 'free'
    STATUS_OCCUPIED = 'occupied'
    STATUS_DISABLED = 'disabled'
    STATUS_CHOICES = (
        (STATUS_FREE, '空闲'),
        (STATUS_OCCUPIED, '占用'),
        (STATUS_DISABLED, '停用'),
    )

    room = models.ForeignKey(DormRoom, verbose_name='寝室',
                             on_delete=models.CASCADE, related_name='beds')
    number = models.SmallIntegerField('床位号')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_FREE)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '床位'
        constraints = [
            models.UniqueConstraint(fields=['room', 'number'],
                                    name='dorm_uniq_room_bed'),
        ]
        ordering = ['room', 'number']

    def __str__(self):
        return '{}#{}'.format(self.room_id, self.number)


class DormAssignment(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_CHECKED_OUT = 'checked_out'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, '在住'),
        (STATUS_CHECKED_OUT, '已退宿'),
    )

    student = models.ForeignKey(
        StudentRecord, verbose_name='学生', on_delete=models.PROTECT,
        related_name='dorm_assignments')
    bed = models.ForeignKey(Bed, verbose_name='床位', on_delete=models.PROTECT,
                            related_name='assignments')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_ACTIVE)
    #: 活跃=1，历史=NULL（MySQL 无部分唯一索引，用 NULL 规避唯一冲突）
    active_slot = models.SmallIntegerField(null=True, blank=True, default=1)
    checkin_at = models.DateTimeField('入住时间', null=True, blank=True)
    checkout_at = models.DateTimeField('退宿时间', null=True, blank=True)
    batch_code = models.CharField('批次', max_length=64, blank=True, default='')
    note = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '住宿关系'
        constraints = [
            models.UniqueConstraint(fields=['student', 'active_slot'],
                                    name='dorm_uniq_active_student'),
            models.UniqueConstraint(fields=['bed', 'active_slot'],
                                    name='dorm_uniq_active_bed'),
        ]
        indexes = [models.Index(fields=['status', 'active_slot'])]

    def __str__(self):
        return '{} @ {}'.format(self.student_id, self.bed_id)


class DormChangeRequest(models.Model):
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, '待审批'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_COMPLETED, '已调宿'),
    )

    student = models.ForeignKey(
        StudentRecord, verbose_name='学生', on_delete=models.PROTECT,
        related_name='dorm_change_requests')
    from_bed = models.ForeignKey(
        Bed, verbose_name='原床位', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='change_from')
    to_bed = models.ForeignKey(
        Bed, verbose_name='目标床位', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='change_to')
    reason = models.CharField('申请理由', max_length=500)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_SUBMITTED)
    submitted_by = models.CharField('申请人', max_length=32, blank=True,
                                    default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True,
                                   default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True,
                                     default='')
    created_at = models.DateTimeField('申请时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '调宿申请'
        indexes = [models.Index(fields=['status', '-created_at'])]


class DormCheckoutRequest(models.Model):
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, '待审批'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已驳回'),
        (STATUS_COMPLETED, '已退宿'),
    )

    student = models.ForeignKey(
        StudentRecord, verbose_name='学生', on_delete=models.PROTECT,
        related_name='dorm_checkout_requests')
    assignment = models.ForeignKey(
        DormAssignment, verbose_name='住宿关系', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='checkout_requests')
    reason = models.CharField('退宿原因', max_length=500)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_SUBMITTED)
    reviewed_by = models.CharField('审批人', max_length=32, blank=True,
                                   default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    created_at = models.DateTimeField('申请时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '退宿申请'
        indexes = [models.Index(fields=['status', '-created_at'])]


class DormRepair(models.Model):
    STATUS_SUBMITTED = 'submitted'
    STATUS_ASSIGNED = 'assigned'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, '待分派'),
        (STATUS_ASSIGNED, '已分派'),
        (STATUS_PROCESSING, '处理中'),
        (STATUS_DONE, '已处理'),
        (STATUS_CLOSED, '已关闭'),
    )

    room = models.ForeignKey(DormRoom, verbose_name='寝室',
                             on_delete=models.CASCADE, related_name='repairs')
    bed = models.ForeignKey(Bed, verbose_name='床位', null=True, blank=True,
                            on_delete=models.SET_NULL, related_name='repairs')
    student = models.ForeignKey(
        StudentRecord, verbose_name='报修学生', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='dorm_repairs')
    description = models.CharField('问题描述', max_length=500)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_SUBMITTED)
    assignee = models.CharField('处理人', max_length=32, blank=True, default='')
    created_by = models.CharField('提交人', max_length=32, blank=True,
                                  default='')
    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    done_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        verbose_name = '宿舍报修'
        indexes = [models.Index(fields=['status', '-created_at'])]


class DormInspection(models.Model):
    RESULT_OK = 'ok'
    RESULT_ISSUE = 'issue'
    RESULT_CHOICES = ((RESULT_OK, '正常'), (RESULT_ISSUE, '发现问题'))

    STATUS_RECORDED = 'recorded'
    STATUS_RECTIFYING = 'rectifying'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = (
        (STATUS_RECORDED, '已记录'),
        (STATUS_RECTIFYING, '整改中'),
        (STATUS_CLOSED, '已关闭'),
    )

    building = models.ForeignKey(DormBuilding, verbose_name='宿舍楼',
                                 on_delete=models.CASCADE,
                                 related_name='inspections')
    room = models.ForeignKey(DormRoom, verbose_name='寝室', null=True,
                             blank=True, on_delete=models.SET_NULL,
                             related_name='inspections')
    items = models.JSONField('检查项', default=dict, blank=True)
    result = models.CharField('结论', max_length=16, choices=RESULT_CHOICES,
                              default=RESULT_OK)
    issue = models.CharField('问题描述', max_length=500, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_RECORDED)
    inspector = models.CharField('检查人', max_length=32, blank=True,
                                 default='')
    created_at = models.DateTimeField('检查时间', auto_now_add=True)

    class Meta:
        verbose_name = '宿舍巡查'
        indexes = [models.Index(fields=['status', '-created_at'])]


class DormManagerScope(models.Model):
    ROLE_SUPERVISOR = 'supervisor'
    ROLE_MANAGER = 'manager'
    ROLE_REPAIR = 'repair'
    ROLE_CHOICES = (
        (ROLE_SUPERVISOR, '宿舍主管'),
        (ROLE_MANAGER, '楼栋宿管'),
        (ROLE_REPAIR, '维修处理'),
    )

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号',
        on_delete=models.CASCADE, related_name='dorm_scopes')
    building = models.ForeignKey(DormBuilding, verbose_name='宿舍楼',
                                 on_delete=models.CASCADE,
                                 related_name='managers')
    role = models.CharField('岗位', max_length=16, choices=ROLE_CHOICES,
                            default=ROLE_MANAGER)
    created_at = models.DateTimeField('授权时间', auto_now_add=True)

    class Meta:
        verbose_name = '宿管范围'
        constraints = [
            models.UniqueConstraint(fields=['account', 'building'],
                                    name='dorm_uniq_account_building'),
        ]

    def __str__(self):
        return '{} -> {}'.format(self.account_id, self.building_id)
