"""R5 服务层： akademik 基础数据的校验与状态变更。

统一原则：
- 日期范围合法性、唯一性、容量与越权全部在**服务层**判定；
- 任课关系的可见性收窄在 ``teacher_sections`` / ``can_teach`` 中实现，
  视图与 API 必须复用；
- 修读关系变更写 ``EnrollmentHistory``。
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
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


# ---------------------------------------------------------------------------
# 学生选课（产品端）
# ---------------------------------------------------------------------------
def available_sections(account, term=None):
    """当前学期可选教学班：开放、未选、容量未满。"""
    term = term or current_term()
    if term is None or account is None:
        return TeachingSection.objects.none()
    taken = list(Enrollment.objects.filter(
        account=account, status=Enrollment.STATUS_ENROLLED).values_list(
        'section_id', flat=True))
    return (TeachingSection.objects
            .filter(term=term, status=TeachingSection.STATUS_OPEN)
            .exclude(pk__in=taken)
            .annotate(enrolled_count=Count(
                'enrollments',
                filter=Q(enrollments__status=Enrollment.STATUS_ENROLLED)))
            .filter(Q(capacity=0) | Q(enrolled_count__lt=F('capacity')))
            .select_related('course', 'term')
            .order_by('course__title', 'code'))


def schedule_conflicts(account, section):
    """教学班时间冲突检测：基于已发布排课批次的 ``ScheduleEntry``。

    同一 (weekday, period) 槽位即视为冲突（保守策略，不区分单双周）。
    无已发布排课或学生尚无选课时返回空列表。
    """
    from smass_academic.models import Enrollment
    from smass_scheduling.models import RUN_PUBLISHED, ScheduleEntry

    if account is None or section is None:
        return []
    section_ids = list(
        Enrollment.objects.filter(account=account)
        .exclude(status='dropped').exclude(section=section)
        .values_list('section_id', flat=True))
    if not section_ids:
        return []
    target_slots = set(
        ScheduleEntry.objects.filter(
            run__status=RUN_PUBLISHED, requirement__section=section)
        .values_list('weekday', 'period'))
    if not target_slots:
        return []
    weekdays = [slot[0] for slot in target_slots]
    periods = [slot[1] for slot in target_slots]
    labels = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日'}
    conflicts = []
    entries = (ScheduleEntry.objects
               .filter(run__status=RUN_PUBLISHED,
                       requirement__section_id__in=section_ids,
                       weekday__in=weekdays, period__in=periods)
               .select_related('requirement__section__course')
               .order_by('weekday', 'period'))
    for entry in entries:
        if (entry.weekday, entry.period) not in target_slots:
            continue
        course = entry.requirement.section.course
        conflicts.append('周{} 第{}节 与《{}》冲突'.format(
            labels.get(entry.weekday, entry.weekday), entry.period,
            getattr(course, 'title', '课程')))
    return conflicts


def enroll_for_student(account, section):
    """学生选课入口：校验学期/状态/冲突后调用 ``enroll``。"""
    if account is None or not getattr(account, 'is_authenticated', False):
        raise AccessError('请先登录')
    if section.status != TeachingSection.STATUS_OPEN:
        raise AcademicError('教学班未开放选课')
    current = current_term()
    if current is not None and section.term_id != current.pk:
        raise AcademicError('只能选当前学期的教学班')
    conflicts = schedule_conflicts(account, section)
    if conflicts:
        raise AcademicError('与已选课程时间冲突：{}'.format('；'.join(conflicts)))
    return enroll(section, account, actor=getattr(account, 'login_name', ''))
