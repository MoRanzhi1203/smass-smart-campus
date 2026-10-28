"""R5 服务层： akademik 基础数据的校验与状态变更。

统一原则：
- 日期范围合法性、唯一性、容量与越权全部在**服务层**判定；
- 任课关系的可见性收窄在 ``teacher_sections`` / ``can_teach`` 中实现，
  视图与 API 必须复用；
- 修读关系变更写 ``EnrollmentHistory``。
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from smass_academic.models import (
    AcademicTerm,
    AcademicYear,
    Course,
    Enrollment,
    EnrollmentHistory,
    TeachingAssignment,
    TeachingSection,
)


class AcademicError(Exception):
    """教学域错误基类。"""


class DateRangeError(AcademicError):
    """日期范围不合法。"""


class DuplicateError(AcademicError):
    """唯一约束冲突。"""


class CapacityError(AcademicError):
    """容量不足。"""


class AccessError(AcademicError):
    """越权。"""


def _check_range(start, end, label):
    if start is None or end is None:
        raise DateRangeError('{}：起止日期不能为空'.format(label))
    if end <= start:
        raise DateRangeError('{}：结束日期必须晚于开始日期'.format(label))


# ---------------------------------------------------------------------------
# R5-01 学年 / 学期
# ---------------------------------------------------------------------------
def create_year(code, start_date, end_date, *, is_active=False):
    code = (code or '').strip()
    if not code:
        raise AcademicError('学年编码不能为空')
    _check_range(start_date, end_date, '学年')

    if AcademicYear.objects.filter(code=code).exists():
        raise DuplicateError('学年 {} 已存在'.format(code))

    with transaction.atomic():
        if is_active:
            AcademicYear.objects.filter(is_active=True).update(is_active=False)
        try:
            return AcademicYear.objects.create(
                code=code, start_date=start_date, end_date=end_date,
                is_active=is_active,
            )
        except IntegrityError as exc:
            raise DuplicateError('学年创建冲突: {}'.format(exc))


def activate_year(year):
    with transaction.atomic():
        AcademicYear.objects.filter(is_active=True).exclude(pk=year.pk).update(
            is_active=False
        )
        year.is_active = True
        year.save(update_fields=['is_active'])
    return year


def create_term(year, semester, start_date, end_date, *, name='', is_active=False):
    _check_range(start_date, end_date, '学期')

    if start_date < year.start_date or end_date > year.end_date:
        raise DateRangeError(
            '学期日期必须落在学年 {}（{} ~ {}）范围内'.format(
                year.code, year.start_date, year.end_date
            )
        )

    if AcademicTerm.objects.filter(year=year, semester=semester).exists():
        raise DuplicateError('{} 的学期 {} 已存在'.format(year.code, semester))

    with transaction.atomic():
        if is_active:
            AcademicTerm.objects.filter(is_active=True).update(is_active=False)
        return AcademicTerm.objects.create(
            year=year, semester=semester, name=name,
            start_date=start_date, end_date=end_date, is_active=is_active,
        )


def activate_term(term):
    with transaction.atomic():
        AcademicTerm.objects.filter(is_active=True).exclude(pk=term.pk).update(
            is_active=False
        )
        term.is_active = True
        term.save(update_fields=['is_active'])
    return term


def current_term():
    return AcademicTerm.objects.filter(is_active=True).select_related('year').first()


# ---------------------------------------------------------------------------
# R5-02 课程
# ---------------------------------------------------------------------------
def create_course(code, title, *, credit=None, course_type='', is_active=True):
    code = (code or '').strip()
    title = (title or '').strip()
    if not code or not title:
        raise AcademicError('课程编码与名称不能为空')
    if credit is not None and credit < 0:
        raise AcademicError('学分不能为负')

    if Course.objects.filter(code=code).exists():
        raise DuplicateError('课程 {} 已存在'.format(code))

    return Course.objects.create(
        code=code, title=title, credit=credit,
        course_type=course_type, is_active=is_active,
    )


def search_courses(keyword=None, active_only=False):
    queryset = Course.objects.all().order_by('code')
    if keyword:
        queryset = queryset.filter(
            models_q_title(keyword)
        )
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset


def models_q_title(keyword):
    from django.db.models import Q

    return Q(title__icontains=keyword) | Q(code__icontains=keyword)


# ---------------------------------------------------------------------------
# R5-03 教学班
# ---------------------------------------------------------------------------
def create_section(term, course, code, *, capacity=0):
    code = (code or '').strip()
    if not code:
        raise AcademicError('教学班号不能为空')
    if capacity < 0:
        raise AcademicError('容量不能为负')
    if not course.is_active:
        raise AcademicError('课程已停用，不能开班')
    if not term.year_id:
        raise AcademicError('学期未关联学年')

    if TeachingSection.objects.filter(term=term, course=course, code=code).exists():
        raise DuplicateError('该学期该课程的班号 {} 已存在'.format(code))

    return TeachingSection.objects.create(
        term=term, course=course, code=code, capacity=capacity,
    )


# ---------------------------------------------------------------------------
# R5-04 任课
# ---------------------------------------------------------------------------
def assign_teacher(section, account, *, assigned_by=''):
    if account is None or not getattr(account, 'is_active', False):
        raise AccessError('教师账号无效')

    active = TeachingAssignment.objects.filter(
        section=section, account=account, revoked_at__isnull=True
    ).exists()
    if active:
        raise DuplicateError('该教师已在此教学班任课')

    return TeachingAssignment.objects.create(
        section=section, account=account, assigned_by=assigned_by[:32]
    )


def revoke_assignment(assignment):
    assignment.revoked_at = timezone.now()
    assignment.save(update_fields=['revoked_at'])
    return assignment


def teacher_sections(account):
    """返回该教师当前任课的教学班（撤销即失效）。"""
    if account is None or not getattr(account, 'is_active', False):
        return TeachingSection.objects.none()

    section_ids = TeachingAssignment.objects.filter(
        account=account, revoked_at__isnull=True
    ).values_list('section_id', flat=True)
    return TeachingSection.objects.filter(pk__in=list(section_ids))


def can_teach(account, section):
    return teacher_sections(account).filter(pk=section.pk).exists()


# ---------------------------------------------------------------------------
# R5-05 修读
# ---------------------------------------------------------------------------
def enroll(section, account, *, actor=''):
    """选课：容量与重复校验在同一事务内（依赖唯一约束兜底并发）。"""
    if account is None or not getattr(account, 'is_active', False):
        raise AccessError('学生账号无效')
    if section.status != TeachingSection.STATUS_OPEN:
        raise AcademicError('教学班未开放选课')

    with transaction.atomic():
        existing = Enrollment.objects.filter(section=section, account=account).first()
        if existing is not None and existing.status == Enrollment.STATUS_ENROLLED:
            raise DuplicateError('已选过该教学班')

        if section.capacity:
            enrolled = Enrollment.objects.filter(
                section=section, status=Enrollment.STATUS_ENROLLED
            ).count()
            if enrolled >= section.capacity:
                raise CapacityError('教学班容量已满（{}）'.format(section.capacity))

        if existing is not None:
            old = existing.status
            existing.status = Enrollment.STATUS_ENROLLED
            existing.save(update_fields=['status', 'changed_at'])
            EnrollmentHistory.objects.create(
                enrollment=existing, old_status=old,
                new_status=Enrollment.STATUS_ENROLLED, changed_by=actor[:32],
            )
            return existing

        enrollment = Enrollment.objects.create(
            section=section, account=account, status=Enrollment.STATUS_ENROLLED
        )
        EnrollmentHistory.objects.create(
            enrollment=enrollment, old_status='',
            new_status=Enrollment.STATUS_ENROLLED, changed_by=actor[:32],
        )
        return enrollment


def drop(enrollment, *, actor=''):
    if enrollment.status == Enrollment.STATUS_DROPPED:
        raise DuplicateError('该修读已是退选状态')

    with transaction.atomic():
        old = enrollment.status
        enrollment.status = Enrollment.STATUS_DROPPED
        enrollment.save(update_fields=['status', 'changed_at'])
        EnrollmentHistory.objects.create(
            enrollment=enrollment, old_status=old,
            new_status=Enrollment.STATUS_DROPPED, changed_by=actor[:32],
        )
    return enrollment


def student_sections(account):
    """学生当前修读的教学班（仅 enrolled）。"""
    if account is None or not getattr(account, 'is_active', False):
        return TeachingSection.objects.none()

    section_ids = Enrollment.objects.filter(
        account=account, status=Enrollment.STATUS_ENROLLED
    ).values_list('section_id', flat=True)
    return TeachingSection.objects.filter(pk__in=list(section_ids))


def section_roster(section, account):
    """教学班名册：只有任课教师或全局角色可见。"""
    roles = set(account.active_roles()) if account is not None and account.is_active else set()
    if 'system_admin' in roles or 'college_admin' in roles:
        return Enrollment.objects.filter(section=section)
    if can_teach(account, section):
        return Enrollment.objects.filter(section=section)
    raise AccessError('无权查看该教学班名册')
