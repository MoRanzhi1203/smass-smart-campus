"""R5：教学管理基础数据（学年/学期/课程/教学班/任课/修读）。

设计约束（D02/D11）：
- 业务实体**唯一权威写入来源**就是本模块的表，不与 `app01` 旧课程概念双写；
- 与 `app01` 的对应关系仅在需要时通过适配层显式映射，不隐式同步；
- 所有写操作走服务层校验，视图不做业务判断。
"""
from django.db import models
from django.db.models import Q


class AcademicYear(models.Model):
    """学年，例如 2025-2026。"""

    code = models.CharField('学年编码', max_length=16, unique=True)
    start_date = models.DateField('开始日期')
    end_date = models.DateField('结束日期')
    is_active = models.BooleanField('当前学年', default=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '学年'
        indexes = [models.Index(fields=['is_active', 'start_date'])]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gt=models.F('start_date')),
                name='r5_year_range_valid',
            ),
            # 同一时刻只允许一个"当前学年"（部分唯一索引）
            models.UniqueConstraint(
                fields=['is_active'],
                condition=Q(is_active=True),
                name='r5_uniq_active_year',
            ),
        ]

    def __str__(self):
        return self.code


class AcademicTerm(models.Model):
    """学期，隶属于学年。"""

    SEMESTER_CHOICES = (('1', '第一学期'), ('2', '第二学期'), ('S', '暑期'))

    year = models.ForeignKey(
        AcademicYear, verbose_name='学年', on_delete=models.CASCADE,
        related_name='terms',
    )
    semester = models.CharField('学期', max_length=1, choices=SEMESTER_CHOICES)
    name = models.CharField('显示名', max_length=32, blank=True, default='')
    start_date = models.DateField('开始日期')
    end_date = models.DateField('结束日期')
    is_active = models.BooleanField('当前学期', default=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '学期'
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'semester'], name='r5_uniq_term_per_year'
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=models.F('start_date')),
                name='r5_term_range_valid',
            ),
            models.UniqueConstraint(
                fields=['is_active'],
                condition=Q(is_active=True),
                name='r5_uniq_active_term',
            ),
        ]
        indexes = [models.Index(fields=['year', 'semester'])]

    def __str__(self):
        return '{}-{}'.format(self.year.code, self.semester)


class Course(models.Model):
    """课程目录。"""

    code = models.CharField('课程编码', max_length=32, unique=True)
    title = models.CharField('课程名称', max_length=128)
    # 学分与类型是**可配置数据**，不是政策默认值（D05）
    credit = models.DecimalField('学分', max_digits=4, decimal_places=1,
                                 null=True, blank=True)
    course_type = models.CharField('课程类型', max_length=32, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '课程'
        indexes = [models.Index(fields=['is_active', 'code'])]

    def __str__(self):
        return '{} {}'.format(self.code, self.title)


class TeachingSection(models.Model):
    """教学班（某学期开设的某课程）。"""

    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = ((STATUS_OPEN, '开放'), (STATUS_CLOSED, '关闭'))

    term = models.ForeignKey(
        AcademicTerm, verbose_name='学期', on_delete=models.PROTECT,
        related_name='sections',
    )
    course = models.ForeignKey(
        Course, verbose_name='课程', on_delete=models.PROTECT,
        related_name='sections',
    )
    code = models.CharField('教学班号', max_length=32)
    capacity = models.IntegerField('容量', default=0, help_text='0 表示不限制')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '教学班'
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'course', 'code'], name='r5_uniq_section_code'
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=0), name='r5_section_capacity_nonneg'
            ),
        ]
        indexes = [models.Index(fields=['term', 'status'])]

    def __str__(self):
        return '{} {}'.format(self.term, self.code)


class TeachingAssignment(models.Model):
    """任课关系（教师 × 教学班），支持撤销与历史。"""

    section = models.ForeignKey(
        TeachingSection, verbose_name='教学班', on_delete=models.CASCADE,
        related_name='assignments',
    )
    account = models.ForeignKey(
        'r21_account.Account', verbose_name='教师账号',
        on_delete=models.CASCADE, related_name='teaching_assignments',
    )
    assigned_at = models.DateTimeField('分配时间', auto_now_add=True)
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)
    assigned_by = models.CharField('分配人', max_length=32, blank=True, default='')

    class Meta:
        verbose_name = '任课关系'
        constraints = [
            models.UniqueConstraint(
                fields=['section', 'account'],
                condition=Q(revoked_at__isnull=True),
                name='r5_uniq_active_assignment',
            ),
        ]
        indexes = [models.Index(fields=['account', 'revoked_at'])]


class Enrollment(models.Model):
    """学生修读关系。"""

    STATUS_ENROLLED = 'enrolled'
    STATUS_DROPPED = 'dropped'
    STATUS_CHOICES = ((STATUS_ENROLLED, '已选'), (STATUS_DROPPED, '已退'))

    section = models.ForeignKey(
        TeachingSection, verbose_name='教学班', on_delete=models.CASCADE,
        related_name='enrollments',
    )
    account = models.ForeignKey(
        'r21_account.Account', verbose_name='学生账号',
        on_delete=models.CASCADE, related_name='enrollments',
    )
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES,
                              default=STATUS_ENROLLED)
    enrolled_at = models.DateTimeField('选课时间', auto_now_add=True)
    changed_at = models.DateTimeField('状态变更时间', auto_now=True)

    class Meta:
        verbose_name = '修读关系'
        constraints = [
            models.UniqueConstraint(
                fields=['section', 'account'], name='r5_uniq_enrollment'
            ),
        ]
        indexes = [models.Index(fields=['section', 'status'])]


class EnrollmentHistory(models.Model):
    """修读状态变更历史（append-only）。"""

    enrollment = models.ForeignKey(
        Enrollment, verbose_name='修读', on_delete=models.CASCADE,
        related_name='history',
    )
    old_status = models.CharField('原状态', max_length=16, blank=True, default='')
    new_status = models.CharField('新状态', max_length=16)
    changed_by = models.CharField('操作者', max_length=32, blank=True, default='')
    changed_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '修读历史'
        indexes = [models.Index(fields=['enrollment', 'changed_at'])]
