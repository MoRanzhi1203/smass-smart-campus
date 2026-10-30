"""R14：第二课堂、志愿服务与活动管理（隔离模块）。

设计约定
--------
1. 活动按"类别"组织：第二课堂 / 志愿服务 / 讲座 / 社团活动；
2. 报名有容量与候补：满员进候补，取消后按报名顺序自动递补；
3. 活动签到用服务端生成的签到码，仅在活动进行中有效；
4. 活动关闭时未签到报名者自动标缺勤；
5. 学分为"活动关闭 → 生成待认定 → 审批 → 计入累计"，
   认定数量由活动配置决定（学分 / 志愿时长）；
6. 所有写操作走服务层，审批禁止自批。
"""
from __future__ import annotations

from django.db import models


# ---------------------------------------------------------------------------
# 活动
# ---------------------------------------------------------------------------
CATEGORY_SECOND_CLASS = 'second_class'
CATEGORY_VOLUNTEER = 'volunteer'
CATEGORY_LECTURE = 'lecture'
CATEGORY_CLUB = 'club'
CATEGORY_TYPES = (
    (CATEGORY_SECOND_CLASS, '第二课堂'),
    (CATEGORY_VOLUNTEER, '志愿服务'),
    (CATEGORY_LECTURE, '讲座报告'),
    (CATEGORY_CLUB, '社团活动'),
)

STATUS_DRAFT = 'draft'
STATUS_PUBLISHED = 'published'
STATUS_CLOSED = 'closed'
STATUS_CANCELLED = 'cancelled'
ACTIVITY_STATUS = (
    (STATUS_DRAFT, '草稿'),
    (STATUS_PUBLISHED, '已发布'),
    (STATUS_CLOSED, '已结束'),
    (STATUS_CANCELLED, '已取消'),
)


class Activity(models.Model):
    title = models.CharField('活动名称', max_length=100)
    category = models.CharField('类别', max_length=16, choices=CATEGORY_TYPES,
                                default=CATEGORY_SECOND_CLASS)
    organizer = models.ForeignKey(
        'r21_account.Account', verbose_name='组织者',
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name='organized_activities')
    location = models.CharField('地点', max_length=100, blank=True, default='')

    start_at = models.DateTimeField('开始时间')
    end_at = models.DateTimeField('结束时间')
    registration_deadline = models.DateTimeField('报名截止', null=True, blank=True)
    capacity = models.PositiveIntegerField('容量', default=0,
                                           help_text='0 表示不限')

    credit_points = models.DecimalField('第二课堂学分', max_digits=6, decimal_places=2,
                                        default=0)
    volunteer_hours = models.DecimalField('志愿时长（小时）', max_digits=6, decimal_places=1,
                                          default=0)

    status = models.CharField('状态', max_length=16, choices=ACTIVITY_STATUS,
                              default=STATUS_DRAFT)
    checkin_code = models.CharField('签到码', max_length=8, blank=True, default='')
    checkin_expires_at = models.DateTimeField('签到码过期时间', null=True, blank=True)

    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '活动'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', 'start_at']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.title, self.get_category_display())


# ---------------------------------------------------------------------------
# 报名
# ---------------------------------------------------------------------------
REG_REGISTERED = 'registered'
REG_WAITLISTED = 'waitlisted'
REG_CANCELLED = 'cancelled'
REG_CHECKED_IN = 'checked_in'
REG_ABSENT = 'absent'
REGISTRATION_STATUS = (
    (REG_REGISTERED, '已报名'),
    (REG_WAITLISTED, '候补中'),
    (REG_CANCELLED, '已取消'),
    (REG_CHECKED_IN, '已签到'),
    (REG_ABSENT, '缺勤'),
)

#: 占用容量的状态
OCCUPYING_STATUSES = (REG_REGISTERED, REG_CHECKED_IN, REG_ABSENT)


class ActivityRegistration(models.Model):
    activity = models.ForeignKey(
        Activity, verbose_name='活动', on_delete=models.CASCADE,
        related_name='registrations')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='activity_registrations')
    status = models.CharField('状态', max_length=16, choices=REGISTRATION_STATUS,
                              default=REG_REGISTERED)
    registered_at = models.DateTimeField('报名时间', auto_now_add=True)
    checked_in_at = models.DateTimeField('签到时间', null=True, blank=True)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '活动报名'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['activity', 'record'], name='r14_uniq_activity_record'),
        ]
        indexes = [
            models.Index(fields=['activity', 'status']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '{} @ {}'.format(self.record.student_no, self.activity_id)


# ---------------------------------------------------------------------------
# 学分/时长认定
# ---------------------------------------------------------------------------
CREDIT_PENDING = 'pending'
CREDIT_APPROVED = 'approved'
CREDIT_REJECTED = 'rejected'
CREDIT_STATUS = (
    (CREDIT_PENDING, '待认定'),
    (CREDIT_APPROVED, '已认定'),
    (CREDIT_REJECTED, '已驳回'),
)


class ActivityCredit(models.Model):
    activity = models.ForeignKey(
        Activity, verbose_name='活动', on_delete=models.CASCADE,
        related_name='credits')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='activity_credits')
    category = models.CharField('类别', max_length=16, choices=CATEGORY_TYPES)
    points = models.DecimalField('学分', max_digits=6, decimal_places=2, default=0)
    hours = models.DecimalField('志愿时长', max_digits=6, decimal_places=1, default=0)

    status = models.CharField('状态', max_length=16, choices=CREDIT_STATUS,
                              default=CREDIT_PENDING)
    reviewed_by = models.CharField('认定人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('认定时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '活动认定'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['activity', 'record'], name='r14_uniq_credit_activity_record'),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '{} {} 学分'.format(self.record.student_no, self.points)
