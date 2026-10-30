"""R11 排课数据模型。

覆盖主任务书 R11 的建模需求：
- 教学日历 / 教学周（复用 ``smass_academic.AcademicTerm``）；
- 课时需求（``LessonRequirement``：每周次数、每次节数、学生数、教室类型）；
- 教师可用性与**已批准的特殊约束**（``TeacherAvailability`` / ``TeacherConstraint``）；
- 修读群体（``Cohort``）用于学生冲突判定；
- 排课批次（``ScheduleRun``）与结果（``ScheduleEntry``）；
- 冲突解释（``ScheduleConflict``）。

设计约定
--------
1. **不臆造职称权限**：教师类型（教授/副教授/讲师/实验员/行政双肩挑/外聘）
   只作为**可配置的课时上限依据**，不因职称自动获得任何额外权利。
2. 时间用 ``(weekday, period)`` 表示，具体钟点由 ``TimeSlot`` 定义；
   这样排课算法与"第几节课"解耦，换作息时间不需要重排。
3. 结果表上的唯一约束把**硬约束**下沉到数据库：
   ``(run, room, weekday, period)``、``(run, teacher, weekday, period)``、
   ``(run, cohort, weekday, period)`` 各自唯一。
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
RUN_DRAFT = 'draft'
RUN_SOLVED = 'solved'
RUN_INFEASIBLE = 'infeasible'
RUN_PUBLISHED = 'published'
RUN_ARCHIVED = 'archived'
RUN_STATUS_CHOICES = (
    (RUN_DRAFT, '草稿'),
    (RUN_SOLVED, '已求解'),
    (RUN_INFEASIBLE, '不可行'),
    (RUN_PUBLISHED, '已发布'),
    (RUN_ARCHIVED, '已归档'),
)

CONSTRAINT_UNAVAILABLE = 'unavailable'
CONSTRAINT_PREFER = 'prefer'
CONSTRAINT_AVOID = 'avoid'
CONSTRAINT_KIND_CHOICES = (
    (CONSTRAINT_UNAVAILABLE, '不可用（硬约束）'),
    (CONSTRAINT_PREFER, '偏好（软约束）'),
    (CONSTRAINT_AVOID, '回避（软约束）'),
)

#: 教师类型对角色的影响：仅用于可配置的周课时上限，不授予任何权限
INSTRUCTOR_PROFESSOR = 'professor'
INSTRUCTOR_ASSOCIATE = 'associate_professor'
INSTRUCTOR_LECTURER = 'lecturer'
INSTRUCTOR_LAB = 'lab_teacher'
INSTRUCTOR_ADMIN_DUAL = 'admin_dual'
INSTRUCTOR_VISITING = 'visiting'
INSTRUCTOR_TYPE_CHOICES = (
    (INSTRUCTOR_PROFESSOR, '教授'),
    (INSTRUCTOR_ASSOCIATE, '副教授'),
    (INSTRUCTOR_LECTURER, '讲师'),
    (INSTRUCTOR_LAB, '实验员'),
    (INSTRUCTOR_ADMIN_DUAL, '行政双肩挑'),
    (INSTRUCTOR_VISITING, '外聘/兼职'),
)

#: 默认周课时上限（可由 settings.SCHEDULING_WORKLOAD_CAPS 覆盖）
DEFAULT_WORKLOAD_CAPS = {
    INSTRUCTOR_PROFESSOR: 12,
    INSTRUCTOR_ASSOCIATE: 14,
    INSTRUCTOR_LECTURER: 16,
    INSTRUCTOR_LAB: 18,
    INSTRUCTOR_ADMIN_DUAL: 6,
    INSTRUCTOR_VISITING: 8,
}

#: 默认硬冲突权重（用于解释与评估）
HARD_CONFLICT_TYPES = (
    'teacher_double_booked',
    'room_double_booked',
    'cohort_double_booked',
    'teacher_unavailable',
    'room_unavailable',
    'room_capacity',
    'room_type_mismatch',
    'room_maintenance',
    'workload_exceeded',
    'session_count_mismatch',
)


# ---------------------------------------------------------------------------
# 时间槽
# ---------------------------------------------------------------------------
class TimeSlot(models.Model):
    """作息时间槽：第几节课在第几天、几点到几点。"""

    weekday = models.SmallIntegerField('星期', help_text='0=周一 … 6=周日')
    period = models.SmallIntegerField('节次', help_text='1 开始')
    start_time = models.TimeField('开始时间')
    end_time = models.TimeField('结束时间')
    label = models.CharField('显示名', max_length=32, blank=True, default='')

    class Meta:
        db_table = 'smass_scheduling_timeslot'
        verbose_name = '时间槽'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['weekday', 'period'], name='r11_uniq_timeslot'),
            models.CheckConstraint(condition=Q(period__gte=1),
                                   name='r11_period_positive'),
            models.CheckConstraint(condition=Q(weekday__gte=0) & Q(weekday__lte=6),
                                   name='r11_weekday_range'),
        ]
        ordering = ['weekday', 'period']

    def __str__(self):
        return '周{}第{}节'.format(self.weekday + 1, self.period)


class TeacherProfile(models.Model):
    """教师排课属性（与 r21 Account 一对一）。

    ``instructor_type`` 只影响**默认周课时上限**，不产生任何权限。
    """

    account = models.OneToOneField(
        'r21_account.Account', verbose_name='账号',
        on_delete=models.CASCADE, related_name='scheduling_profile')
    instructor_type = models.CharField(
        '教师类型', max_length=24, choices=INSTRUCTOR_TYPE_CHOICES,
        default=INSTRUCTOR_LECTURER)
    weekly_hour_cap = models.IntegerField(
        '周课时上限', default=0, help_text='0 表示按教师类型的默认值')
    max_daily_periods = models.IntegerField(
        '单日最大节数', default=0, help_text='0 表示不限制')
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        db_table = 'smass_scheduling_teacher_profile'
        verbose_name = '教师排课属性'
        verbose_name_plural = verbose_name

    def effective_cap(self):
        if self.weekly_hour_cap:
            return self.weekly_hour_cap
        from django.conf import settings

        caps = dict(DEFAULT_WORKLOAD_CAPS)
        caps.update(getattr(settings, 'SCHEDULING_WORKLOAD_CAPS', None) or {})
        return caps.get(self.instructor_type, 16)


class TeacherAvailability(models.Model):
    """教师可用时段。

    语义：**只要存在任何一行**，就表示"仅这些时段可用"；
    完全没有记录则视为"按约束表判断（默认全可用）"。
    """

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='教师',
        on_delete=models.CASCADE, related_name='scheduling_availability')
    weekday = models.SmallIntegerField('星期')
    period = models.SmallIntegerField('节次')

    class Meta:
        db_table = 'smass_scheduling_availability'
        verbose_name = '教师可用时段'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'weekday', 'period'],
                name='r11_uniq_teacher_availability'),
        ]
        indexes = [models.Index(fields=['account', 'weekday'])]


class TeacherConstraint(models.Model):
    """教师特殊约束（必须**已批准**才参与求解）。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='教师',
        on_delete=models.CASCADE, related_name='scheduling_constraints')
    kind = models.CharField('类型', max_length=16, choices=CONSTRAINT_KIND_CHOICES)
    weekday = models.SmallIntegerField('星期')
    period = models.SmallIntegerField('节次')
    reason = models.CharField('原因', max_length=200, blank=True, default='')
    approved_by = models.CharField('批准人', max_length=32, blank=True, default='')
    approved_at = models.DateTimeField('批准时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'smass_scheduling_teacher_constraint'
        verbose_name = '教师特殊约束'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['account', 'kind'])]

    @property
    def approved(self):
        return bool(self.approved_by)


# ---------------------------------------------------------------------------
# 修读群体
# ---------------------------------------------------------------------------
class Cohort(models.Model):
    """修读群体（行政班 / 选课群体）。

    同一 cohort 在同一个时间槽内只能有一门课——这是"学生冲突"的可实施近似。
    """

    code = models.CharField('群体编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=100)
    size = models.IntegerField('人数', default=0)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        db_table = 'smass_scheduling_cohort'
        verbose_name = '修读群体'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


# ---------------------------------------------------------------------------
# 排课批次与需求
# ---------------------------------------------------------------------------
class ScheduleRun(models.Model):
    """一次排课求解批次。"""

    term = models.ForeignKey(
        'smass_academic.AcademicTerm', verbose_name='学期',
        on_delete=models.CASCADE, related_name='schedule_runs')
    status = models.CharField('状态', max_length=16, choices=RUN_STATUS_CHOICES,
                              default=RUN_DRAFT)
    algorithm = models.CharField('算法', max_length=64, blank=True, default='')
    seed = models.IntegerField('随机种子', default=0)

    #: 求解评估
    hard_conflicts = models.IntegerField('硬冲突数', default=0)
    soft_cost = models.IntegerField('软成本', default=0)
    placed_sessions = models.IntegerField('已排节次', default=0)
    required_sessions = models.IntegerField('所需节次', default=0)

    #: 不可行时的解释（人类可读，逐条）
    explanation = models.JSONField('求解说明', default=list, blank=True)
    created_by = models.CharField('创建者', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)

    class Meta:
        db_table = 'smass_scheduling_run'
        verbose_name = '排课批次'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['term', 'status'])]
        ordering = ['-created_at']

    def __str__(self):
        return '{} {}'.format(self.term_id, self.status)


class LessonRequirement(models.Model):
    """教学班的上课需求。"""

    run = models.ForeignKey(
        ScheduleRun, verbose_name='排课批次', on_delete=models.CASCADE,
        related_name='requirements')
    section = models.ForeignKey(
        'smass_academic.TeachingSection', verbose_name='教学班',
        on_delete=models.CASCADE, related_name='scheduling_requirements')
    teacher = models.ForeignKey(
        'r21_account.Account', verbose_name='主讲教师',
        on_delete=models.PROTECT, related_name='scheduling_requirements')
    cohort = models.ForeignKey(
        Cohort, verbose_name='修读群体', on_delete=models.PROTECT,
        related_name='requirements')

    weekly_sessions = models.IntegerField('每周次数', default=1)
    session_periods = models.IntegerField('每次节数', default=2)
    students = models.IntegerField('学生数', default=0)
    required_room_type = models.CharField('要求教室类型', max_length=16,
                                          blank=True, default='')
    priority = models.IntegerField('优先级', default=0,
                                   help_text='数值越大越先分配')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'smass_scheduling_requirement'
        verbose_name = '课时需求'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=['run', 'section'],
                                    name='r11_uniq_run_section'),
            models.CheckConstraint(condition=Q(weekly_sessions__gte=1),
                                   name='r11_weekly_sessions_positive'),
            models.CheckConstraint(condition=Q(session_periods__gte=1),
                                   name='r11_session_periods_positive'),
        ]
        ordering = ['-priority', 'pk']

    @property
    def total_sessions(self):
        return self.weekly_sessions * self.session_periods

    def __str__(self):
        return '{} x{}'.format(self.section_id, self.weekly_sessions)


class ScheduleEntry(models.Model):
    """排课结果：一个需求在某个时间槽占用某间教室。"""

    run = models.ForeignKey(
        ScheduleRun, verbose_name='排课批次', on_delete=models.CASCADE,
        related_name='entries')
    requirement = models.ForeignKey(
        LessonRequirement, verbose_name='课时需求', on_delete=models.CASCADE,
        related_name='entries')
    room = models.ForeignKey(
        'smass_facilities.Room', verbose_name='教室', on_delete=models.PROTECT,
        related_name='schedule_entries')
    teacher = models.ForeignKey(
        'r21_account.Account', verbose_name='教师', on_delete=models.PROTECT,
        related_name='schedule_entries')
    cohort = models.ForeignKey(
        Cohort, verbose_name='修读群体', on_delete=models.PROTECT,
        related_name='schedule_entries')

    weekday = models.SmallIntegerField('星期')
    period = models.SmallIntegerField('节次')
    #: 该节次属于本次课的"第几次"（1..weekly_sessions），便于展示
    session_index = models.IntegerField('第几次课', default=1)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'smass_scheduling_entry'
        verbose_name = '排课结果'
        verbose_name_plural = verbose_name
        constraints = [
            # 硬约束下沉到数据库
            models.UniqueConstraint(
                fields=['run', 'room', 'weekday', 'period'],
                name='r11_uniq_room_slot'),
            models.UniqueConstraint(
                fields=['run', 'teacher', 'weekday', 'period'],
                name='r11_uniq_teacher_slot'),
            models.UniqueConstraint(
                fields=['run', 'cohort', 'weekday', 'period'],
                name='r11_uniq_cohort_slot'),
            models.UniqueConstraint(
                fields=['run', 'requirement', 'weekday', 'period'],
                name='r11_uniq_requirement_slot'),
        ]
        indexes = [
            models.Index(fields=['run', 'weekday', 'period']),
            models.Index(fields=['run', 'teacher']),
            models.Index(fields=['run', 'room']),
        ]

    def __str__(self):
        return '{} 周{}第{}节 {}'.format(
            self.requirement_id, self.weekday + 1, self.period, self.room_id)


class ScheduleConflict(models.Model):
    """冲突/不可行解释。

    求解失败或局部复核发现冲突时逐条落库，供人工处理，
    而不是只返回一句"排不出来"。
    """

    run = models.ForeignKey(
        ScheduleRun, verbose_name='排课批次', on_delete=models.CASCADE,
        related_name='conflicts')
    requirement = models.ForeignKey(
        LessonRequirement, verbose_name='课时需求', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='conflicts')
    kind = models.CharField('冲突类型', max_length=48)
    weekday = models.IntegerField('星期', null=True, blank=True)
    period = models.IntegerField('节次', null=True, blank=True)
    detail = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'smass_scheduling_conflict'
        verbose_name = '排课冲突'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['run', 'kind'])]

    def __str__(self):
        return '{} {}'.format(self.kind, self.detail)
