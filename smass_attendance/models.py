"""R13：签到考勤、请假销假与补签（隔离模块）。

设计约定
--------
1. **考勤对象是行政班**：``OrganizationUnit(unit_type='class')`` +
   ``smass_organization.StudentRecord``，不依赖排课结果（R11 尚未落教学班选课）；
2. **签到码服务端生成**：6 位数字、带过期时间，客户端提交的码与 session 码比对；
3. **签到幂等**：同一会话同一学生只有一条记录，重复提交返回既有记录；
4. **关闭会话自动补缺勤**：关闭时把该班未签到的在读学生标记为缺勤（可再审）；
5. **请假/补签都是提交 → 审批**，审批人不得是提交人（S12 职责分离）；
6. **请假重叠禁止**：同一学生的时间区间不得与已批准的请假重叠（服务层行锁内校验）。
"""
from __future__ import annotations

from django.db import models

# ---------------------------------------------------------------------------
# 考勤会话
# ---------------------------------------------------------------------------
SESSION_OPEN = 'open'
SESSION_CLOSED = 'closed'
SESSION_STATUS = (
    (SESSION_OPEN, '进行中'),
    (SESSION_CLOSED, '已关闭'),
)

RECORD_PRESENT = 'present'
RECORD_LATE = 'late'
RECORD_ABSENT = 'absent'
RECORD_LEAVE = 'leave'
RECORD_STATUS = (
    (RECORD_PRESENT, '出勤'),
    (RECORD_LATE, '迟到'),
    (RECORD_ABSENT, '缺勤'),
    (RECORD_LEAVE, '请假'),
)

SOURCE_SELF = 'self'
SOURCE_TEACHER = 'teacher'
SOURCE_MAKEUP = 'makeup'
RECORD_SOURCES = (
    (SOURCE_SELF, '学生自主签到'),
    (SOURCE_TEACHER, '教师标记'),
    (SOURCE_MAKEUP, '补签生效'),
)

#: 缺勤/请假之外算"实际到课"
ATTENDED_STATUSES = (RECORD_PRESENT, RECORD_LATE)


class AttendanceSession(models.Model):
    """一次考勤会话（班级 + 日期 + 节次）。"""

    unit = models.ForeignKey(
        'smass_organization.OrganizationUnit', verbose_name='班级',
        on_delete=models.PROTECT, related_name='attendance_sessions')
    session_date = models.DateField('日期')
    period = models.CharField('节次', max_length=16, default='第1-2节')
    topic = models.CharField('考勤说明', max_length=100, blank=True, default='')

    status = models.CharField('状态', max_length=16, choices=SESSION_STATUS,
                              default=SESSION_OPEN)
    code = models.CharField('签到码', max_length=8, blank=True, default='')
    code_expires_at = models.DateTimeField('签到码过期时间', null=True, blank=True)
    late_after_minutes = models.PositiveSmallIntegerField('迟到判定（分钟）', default=10)

    created_by = models.CharField('发起人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    closed_at = models.DateTimeField('关闭时间', null=True, blank=True)

    class Meta:
        verbose_name = '考勤会话'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['unit', 'session_date', 'period'],
                name='r13_uniq_session_slot'),
        ]
        indexes = [
            models.Index(fields=['unit', '-session_date']),
            models.Index(fields=['status', '-session_date']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.unit.code, self.session_date, self.period)


class AttendanceRecord(models.Model):
    """一个学生在一次会话中的考勤结果。"""

    session = models.ForeignKey(
        AttendanceSession, verbose_name='考勤会话',
        on_delete=models.CASCADE, related_name='records')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='attendance_records')
    status = models.CharField('考勤状态', max_length=16, choices=RECORD_STATUS,
                              default=RECORD_ABSENT)
    source = models.CharField('来源', max_length=16, choices=RECORD_SOURCES,
                              default=SOURCE_TEACHER)
    checked_at = models.DateTimeField('签到时间', null=True, blank=True)
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '考勤记录'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'record'], name='r13_uniq_session_record'),
        ]
        indexes = [
            models.Index(fields=['record', 'status']),
            models.Index(fields=['session', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.record.student_no, self.get_status_display())


# ---------------------------------------------------------------------------
# 请假
# ---------------------------------------------------------------------------
LEAVE_PERSONAL = 'personal'
LEAVE_SICK = 'sick'
LEAVE_OFFICIAL = 'official'
LEAVE_TYPES = (
    (LEAVE_PERSONAL, '事假'),
    (LEAVE_SICK, '病假'),
    (LEAVE_OFFICIAL, '公假'),
)

LEAVE_SUBMITTED = 'submitted'
LEAVE_APPROVED = 'approved'
LEAVE_REJECTED = 'rejected'
LEAVE_CANCELLED = 'cancelled'
LEAVE_CLOSED = 'closed'
LEAVE_STATUS = (
    (LEAVE_SUBMITTED, '待审批'),
    (LEAVE_APPROVED, '已批准'),
    (LEAVE_REJECTED, '已驳回'),
    (LEAVE_CANCELLED, '已撤销'),
    (LEAVE_CLOSED, '已销假'),
)


class LeaveRequest(models.Model):
    """请假申请：提交 → 审批 → 销假。"""

    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='leave_requests')
    leave_type = models.CharField('类型', max_length=16, choices=LEAVE_TYPES,
                                  default=LEAVE_PERSONAL)
    start_date = models.DateField('开始日期')
    end_date = models.DateField('结束日期')
    reason = models.CharField('事由', max_length=500, blank=True, default='')

    status = models.CharField('状态', max_length=16, choices=LEAVE_STATUS,
                              default=LEAVE_SUBMITTED)
    submitted_by = models.CharField('提交人', max_length=32, blank=True, default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    closed_at = models.DateTimeField('销假时间', null=True, blank=True)

    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '请假申请'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['record', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return '{} {} {}~{}'.format(
            self.record.student_no, self.get_leave_type_display(),
            self.start_date, self.end_date)


# ---------------------------------------------------------------------------
# 补签
# ---------------------------------------------------------------------------
MAKEUP_SUBMITTED = 'submitted'
MAKEUP_APPROVED = 'approved'
MAKEUP_REJECTED = 'rejected'
MAKEUP_STATUS = (
    (MAKEUP_SUBMITTED, '待审批'),
    (MAKEUP_APPROVED, '已批准'),
    (MAKEUP_REJECTED, '已驳回'),
)


class MakeupRequest(models.Model):
    """补签申请：针对某个已关闭会话的缺勤/迟到记录。"""

    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='makeup_requests')
    session = models.ForeignKey(
        AttendanceSession, verbose_name='考勤会话',
        on_delete=models.PROTECT, related_name='makeup_requests')
    reason = models.CharField('补签理由', max_length=500)
    status = models.CharField('状态', max_length=16, choices=MAKEUP_STATUS,
                              default=MAKEUP_SUBMITTED)
    submitted_by = models.CharField('提交人', max_length=32, blank=True, default='')
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')

    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '补签申请'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['record', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return '{} 补签 {}'.format(self.record.student_no, self.session_id)
