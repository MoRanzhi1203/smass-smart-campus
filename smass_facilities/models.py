"""R16 校园场地与设备资源（隔离模块）。

覆盖主任务书 R16：
- 楼宇 / 房间 / 座位 / 设备 / 资源；
- 房间可用时段（周内常规 + 维护封闭期）；
- 教室预约、审批、无重叠约束、签到 / 爽约 / 释放；
- 实验室资格与培训（无资格不得预约）；
- 共享日历（同一房间的占用视图）。

设计约定
--------
1. **时间区间不重叠**无法用 MySQL CHECK 表达，因此在**服务层**用
   ``SELECT ... FOR UPDATE`` + 区间判定实现，并在测试里做并发用例。
2. 所有写操作只通过 ``services``，视图不直接 ``objects.create``。
3. 默认拒绝：无资格 / 无权限 / 冲突 / 封闭期 一律拒绝。
4. 本模块不依赖 app01 的旧表，也不修改它们。
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ROOM_TYPE_CLASSROOM = 'classroom'
ROOM_TYPE_LAB = 'lab'
ROOM_TYPE_STUDY = 'study'
ROOM_TYPE_MEETING = 'meeting'
ROOM_TYPE_OTHER = 'other'
ROOM_TYPES = (
    (ROOM_TYPE_CLASSROOM, '教室'),
    (ROOM_TYPE_LAB, '实验室'),
    (ROOM_TYPE_STUDY, '自习室'),
    (ROOM_TYPE_MEETING, '会议室'),
    (ROOM_TYPE_OTHER, '其他'),
)

ROOM_STATUS_OPEN = 'open'
ROOM_STATUS_MAINTENANCE = 'maintenance'
ROOM_STATUS_CLOSED = 'closed'
ROOM_STATUS_CHOICES = (
    (ROOM_STATUS_OPEN, '可预约'),
    (ROOM_STATUS_MAINTENANCE, '维护中'),
    (ROOM_STATUS_CLOSED, '停用'),
)

BOOKING_PENDING = 'pending'
BOOKING_APPROVED = 'approved'
BOOKING_CHECKED_IN = 'checked_in'
BOOKING_NO_SHOW = 'no_show'
BOOKING_CANCELLED = 'cancelled'
BOOKING_RELEASED = 'released'
BOOKING_STATUS_CHOICES = (
    (BOOKING_PENDING, '待审批'),
    (BOOKING_APPROVED, '已批准'),
    (BOOKING_CHECKED_IN, '已签到'),
    (BOOKING_NO_SHOW, '爽约'),
    (BOOKING_CANCELLED, '已取消'),
    (BOOKING_RELEASED, '已释放'),
)

#: 视为"占用房间"的状态（用于冲突检测）
OCCUPYING_STATUSES = (BOOKING_PENDING, BOOKING_APPROVED, BOOKING_CHECKED_IN)


# ---------------------------------------------------------------------------
# 资源
# ---------------------------------------------------------------------------
class Building(models.Model):
    """楼宇。"""

    code = models.CharField('楼宇编码', max_length=32, unique=True)
    name = models.CharField('名称', max_length=100)
    campus = models.CharField('校区', max_length=64, blank=True, default='')
    address = models.CharField('地址', max_length=200, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'smass_facilities_building'
        verbose_name = '楼宇'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['is_active'])]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


class Equipment(models.Model):
    """设备类型（投影仪、实验台等）。"""

    code = models.CharField('设备编码', max_length=32, unique=True)
    name = models.CharField('名称', max_length=64)
    kind = models.CharField('类别', max_length=32, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)

    class Meta:
        db_table = 'smass_facilities_equipment'
        verbose_name = '设备'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


class Room(models.Model):
    """房间（教室 / 实验室 / 自习室 / 会议室）。"""

    code = models.CharField('房间编码', max_length=32, unique=True)
    name = models.CharField('名称', max_length=100)
    building = models.ForeignKey(
        Building, verbose_name='楼宇', on_delete=models.PROTECT,
        related_name='rooms')
    floor = models.CharField('楼层', max_length=16, blank=True, default='')
    room_type = models.CharField('类型', max_length=16, choices=ROOM_TYPES,
                                 default=ROOM_TYPE_CLASSROOM)
    capacity = models.IntegerField('容量', default=0, help_text='0 表示不限制')
    seat_count = models.IntegerField('座位数', default=0, help_text='0 表示未细分座位')
    status = models.CharField('状态', max_length=16, choices=ROOM_STATUS_CHOICES,
                              default=ROOM_STATUS_OPEN)
    #: 是否需要使用资格（实验室通常为 True）
    requires_qualification = models.BooleanField('需要资格', default=False)
    #: 是否需要审批
    requires_approval = models.BooleanField('需要审批', default=False)
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'smass_facilities_room'
        verbose_name = '房间'
        verbose_name_plural = verbose_name
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gte=0),
                                   name='r16_room_capacity_nonneg'),
            models.CheckConstraint(condition=Q(seat_count__gte=0),
                                   name='r16_room_seat_nonneg'),
        ]
        indexes = [
            models.Index(fields=['building', 'room_type']),
            models.Index(fields=['status', 'is_active']),
        ]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)

    @property
    def bookable(self):
        return self.is_active and self.status == ROOM_STATUS_OPEN


class RoomEquipment(models.Model):
    """房间与设备的数量关系。"""

    room = models.ForeignKey(Room, verbose_name='房间',
                             on_delete=models.CASCADE, related_name='equipments')
    equipment = models.ForeignKey(Equipment, verbose_name='设备',
                                  on_delete=models.CASCADE)
    quantity = models.IntegerField('数量', default=1)

    class Meta:
        db_table = 'smass_facilities_room_equipment'
        verbose_name = '房间设备'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=['room', 'equipment'],
                                    name='r16_uniq_room_equipment'),
            models.CheckConstraint(condition=Q(quantity__gte=0),
                                   name='r16_room_equipment_nonneg'),
        ]


class RoomQualification(models.Model):
    """使用资格（实验室培训 / 安全准入）。"""

    room = models.ForeignKey(Room, verbose_name='房间',
                             on_delete=models.CASCADE, related_name='qualifications')
    account = models.ForeignKey('r21_account.Account', verbose_name='账号',
                                on_delete=models.CASCADE,
                                related_name='room_qualifications')
    granted_at = models.DateTimeField('授予时间', auto_now_add=True)
    expires_at = models.DateTimeField('到期时间', null=True, blank=True)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        db_table = 'smass_facilities_qualification'
        verbose_name = '使用资格'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=['room', 'account'],
                                    name='r16_uniq_room_qualification'),
        ]
        indexes = [models.Index(fields=['account', 'room'])]


class RoomAvailability(models.Model):
    """常规可用时段（周内，1 周 7 天 × 时间段）。"""

    room = models.ForeignKey(Room, verbose_name='房间',
                             on_delete=models.CASCADE, related_name='availabilities')
    weekday = models.SmallIntegerField('星期', help_text='0=周一 … 6=周日')
    start_time = models.TimeField('开始时间')
    end_time = models.TimeField('结束时间')

    class Meta:
        db_table = 'smass_facilities_availability'
        verbose_name = '可用时段'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'weekday', 'start_time', 'end_time'],
                name='r16_uniq_room_availability'),
        ]
        indexes = [models.Index(fields=['room', 'weekday'])]

    def __str__(self):
        return '{} 周{} {}-{}'.format(
            self.room_id, self.weekday + 1, self.start_time, self.end_time)


class MaintenanceWindow(models.Model):
    """维护封闭期（绝对时间，期间不允许预约）。"""

    room = models.ForeignKey(Room, verbose_name='房间',
                             on_delete=models.CASCADE, related_name='maintenances')
    start_at = models.DateTimeField('开始')
    end_at = models.DateTimeField('结束')
    reason = models.CharField('原因', max_length=200, blank=True, default='')
    created_by = models.CharField('创建者', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'smass_facilities_maintenance'
        verbose_name = '维护封闭期'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['room', 'start_at'])]


class RoomBooking(models.Model):
    """房间预约。"""

    room = models.ForeignKey(Room, verbose_name='房间',
                             on_delete=models.PROTECT, related_name='bookings')
    account = models.ForeignKey('r21_account.Account', verbose_name='申请人',
                                on_delete=models.PROTECT,
                                related_name='room_bookings')
    purpose = models.CharField('用途', max_length=200)
    start_at = models.DateTimeField('开始')
    end_at = models.DateTimeField('结束')
    status = models.CharField('状态', max_length=16,
                              choices=BOOKING_STATUS_CHOICES,
                              default=BOOKING_PENDING)
    attendees = models.IntegerField('人数', default=0)

    approved_by = models.CharField('审批人', max_length=32, blank=True, default='')
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    checked_in_at = models.DateTimeField('签到时间', null=True, blank=True)
    released_at = models.DateTimeField('释放时间', null=True, blank=True)
    cancel_reason = models.CharField('取消原因', max_length=200, blank=True, default='')

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'smass_facilities_booking'
        verbose_name = '房间预约'
        verbose_name_plural = verbose_name
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F('start_at')),
                                   name='r16_booking_time_order'),
            models.CheckConstraint(condition=Q(attendees__gte=0),
                                   name='r16_booking_attendees_nonneg'),
        ]
        indexes = [
            models.Index(fields=['room', 'start_at', 'end_at']),
            models.Index(fields=['account', 'start_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.room_id, self.start_at, self.account_id)

    @property
    def occupying(self):
        return self.status in OCCUPYING_STATUSES
