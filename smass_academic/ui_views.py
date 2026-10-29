"""U4：R5 教学的浏览器表单与流程视图。

所有写操作走 `smass_academic.services`，本层只负责解析、校验与反馈。
异常统一是 `services.AcademicError` 子类（日期/重复/容量/越权）。
"""
from datetime import date

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from r21_account.models import Account
from smass_academic import services
from smass_academic.models import (
    AcademicTerm,
    AcademicYear,
    Course,
    Enrollment,
    TeachingAssignment,
    TeachingSection,
)
from smass_organization.views import roles_required

ADMIN_ROLES = {'system_admin'}
ACADEMIC_ROLES = {'system_admin', 'college_admin'}
TEACHER_ROLES = {'system_admin', 'college_admin', 'teacher'}


def _actor(request):
    account = getattr(request, 'user', None)
    return getattr(account, 'login_name', '') if account is not None else ''


def _parse_date(value, field, errors):
    text = (value or '').strip()
    if not text:
        errors[field] = '日期不能为空'
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors[field] = '日期格式应为 YYYY-MM-DD'
        return None


def _error_code(exc):
    if isinstance(exc, services.DateRangeError):
        return 'DATE_RANGE'
    if isinstance(exc, services.DuplicateError):
        return 'DUPLICATE'
    if isinstance(exc, services.CapacityError):
        return 'CAPACITY'
    if isinstance(exc, services.AccessError):
        return 'ACCESS'
    return 'INVALID'


# ---------------------------------------------------------------------------
# R5-01 学年
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def year_new(request):
    errors = {}
    form = {'code': '', 'start_date': '', 'end_date': '', 'is_active': False}

    if request.method == 'POST':
        form['code'] = (request.POST.get('code') or '').strip()
        form['is_active'] = bool(request.POST.get('is_active'))
        start = _parse_date(request.POST.get('start_date'), 'start_date', errors)
        end = _parse_date(request.POST.get('end_date'), 'end_date', errors)

        if not form['code']:
            errors['code'] = '学年编码不能为空'

        if not errors:
            try:
                year = services.create_year(
                    form['code'], start, end, is_active=form['is_active'])
            except services.AcademicError as exc:
                errors['general'] = str(exc)
            else:
                messages.success(request, '学年「{}」已创建'.format(year.code))
                return redirect('/r5/years/')

    return render(request, 'r5/year_form.html', {'form': form, 'errors': errors})


# ---------------------------------------------------------------------------
# R5-01 学期
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def term_new(request):
    errors = {}
    form = {'year': '', 'semester': '1', 'name': '',
            'start_date': '', 'end_date': '', 'is_active': False}

    if request.method == 'POST':
        form['year'] = (request.POST.get('year') or '').strip()
        form['semester'] = (request.POST.get('semester') or '').strip()
        form['name'] = (request.POST.get('name') or '').strip()
        form['is_active'] = bool(request.POST.get('is_active'))
        start = _parse_date(request.POST.get('start_date'), 'start_date', errors)
        end = _parse_date(request.POST.get('end_date'), 'end_date', errors)

        year = None
        if form['year']:
            year = AcademicYear.objects.filter(pk=form['year']).first()
            if year is None:
                errors['year'] = '学年不存在'
        else:
            errors['year'] = '必须选择学年'

        if not errors:
            try:
                term = services.create_term(
                    year, form['semester'], start, end,
                    name=form['name'], is_active=form['is_active'])
            except services.AcademicError as exc:
                errors['general'] = str(exc)
                errors['__code__'] = _error_code(exc)
            else:
                messages.success(request, '学期已创建')
                return redirect('/r5/terms/')

    return render(request, 'r5/term_form.html', {
        'form': form,
        'errors': errors,
        'years': AcademicYear.objects.order_by('-start_date')[:50],
        'semesters': [('1', '第一学期'), ('2', '第二学期'), ('S', '暑期')],
    })


# ---------------------------------------------------------------------------
# R5-02 课程
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def course_new(request):
    errors = {}
    form = {'code': '', 'title': '', 'credit': '', 'course_type': '',
            'is_active': True}

    if request.method == 'POST':
        form['code'] = (request.POST.get('code') or '').strip()
        form['title'] = (request.POST.get('title') or '').strip()
        form['credit'] = (request.POST.get('credit') or '').strip()
        form['course_type'] = (request.POST.get('course_type') or '').strip()
        form['is_active'] = bool(request.POST.get('is_active'))

        credit = None
        if form['credit']:
            try:
                credit = float(form['credit'])
            except ValueError:
                errors['credit'] = '学分必须是数字'

        if not errors:
            try:
                course = services.create_course(
                    form['code'], form['title'], credit=credit,
                    course_type=form['course_type'], is_active=form['is_active'])
            except services.AcademicError as exc:
                errors['general'] = str(exc)
            else:
                messages.success(request, '课程「{}」已创建'.format(course.code))
                return redirect('/r5/courses/')

    return render(request, 'r5/course_form.html', {'form': form, 'errors': errors})


# ---------------------------------------------------------------------------
# R5-03 教学班
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def section_new(request):
    errors = {}
    form = {'term': '', 'course': '', 'code': '', 'capacity': '0'}

    if request.method == 'POST':
        form.update({
            'term': (request.POST.get('term') or '').strip(),
            'course': (request.POST.get('course') or '').strip(),
            'code': (request.POST.get('code') or '').strip(),
            'capacity': (request.POST.get('capacity') or '0').strip(),
        })

        term = AcademicTerm.objects.filter(pk=form['term']).first() if form['term'] else None
        course = Course.objects.filter(pk=form['course']).first() if form['course'] else None
        if term is None:
            errors['term'] = '学期不存在'
        if course is None:
            errors['course'] = '课程不存在'

        try:
            capacity = int(form['capacity'] or 0)
        except ValueError:
            capacity = -1
        if capacity < 0:
            errors['capacity'] = '容量必须是非负整数'

        if not errors:
            try:
                section = services.create_section(term, course, form['code'], capacity=capacity)
            except services.AcademicError as exc:
                errors['general'] = str(exc)
            else:
                messages.success(request, '教学班「{}」已创建'.format(section.code))
                return redirect('/r5/sections/')

    return render(request, 'r5/section_form.html', {
        'form': form,
        'errors': errors,
        'terms': AcademicTerm.objects.select_related('year').order_by('-start_date')[:50],
        'courses': Course.objects.filter(is_active=True).order_by('code')[:200],
    })


# ---------------------------------------------------------------------------
# R5-04 任课分配
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ACADEMIC_ROLES)
def section_assign(request, pk):
    section = TeachingSection.objects.filter(pk=pk).select_related('term', 'course').first()
    if section is None:
        return HttpResponse('教学班不存在', status=404)

    errors = {}
    if request.method == 'POST':
        teacher_id = (request.POST.get('teacher') or '').strip()
        teacher = Account.objects.filter(pk=teacher_id).first() if teacher_id else None
        if teacher is None:
            errors['teacher'] = '请选择教师'
        elif not teacher.is_active:
            errors['teacher'] = '该账号已停用'
        else:
            try:
                services.assign_teacher(section, teacher, assigned_by=_actor(request))
            except services.AcademicError as exc:
                errors['general'] = str(exc)
            else:
                messages.success(request, '已分配任课教师')
                return redirect('/r5/sections/{}/assign/'.format(section.pk))

    assignments = TeachingAssignment.objects.filter(
        section=section, revoked_at__isnull=True
    ).select_related('account')

    candidates = Account.objects.filter(is_active=True).order_by('login_name')[:200]

    return render(request, 'r5/section_assign.html', {
        'section': section,
        'assignments': assignments,
        'candidates': candidates,
        'errors': errors,
    })


@require_POST
@roles_required(*ACADEMIC_ROLES)
def assignment_revoke(request, pk):
    assignment = TeachingAssignment.objects.filter(pk=pk).first()
    if assignment is None:
        return HttpResponse('任课记录不存在', status=404)

    services.revoke_assignment(assignment)
    messages.success(request, '已撤销任课')
    return redirect('/r5/sections/{}/assign/'.format(assignment.section_id))


# ---------------------------------------------------------------------------
# R5-05 名册（教师视角）
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def section_roster_page(request, pk):
    section = TeachingSection.objects.filter(pk=pk).select_related('term', 'course').first()
    if section is None:
        return HttpResponse('教学班不存在', status=404)

    account = getattr(request, 'user', None)
    try:
        roster = services.section_roster(section, account)
    except services.AccessError:
        return HttpResponse('无权查看该教学班名册', status=403)

    return render(request, 'r5/roster.html', {
        'section': section,
        'roster': roster.select_related('account'),
        'can_teach': services.can_teach(account, section),
    })


@require_POST
@roles_required(*TEACHER_ROLES)
def roster_drop(request, pk, enrollment_id):
    """教师/管理员将学生退选。"""
    section = TeachingSection.objects.filter(pk=pk).first()
    if section is None:
        return HttpResponse('教学班不存在', status=404)

    account = getattr(request, 'user', None)
    try:
        services.section_roster(section, account)  # 权限检查
        enrollment = Enrollment.objects.filter(pk=enrollment_id, section=section).first()
        if enrollment is None:
            return HttpResponse('修读记录不存在', status=404)
        services.drop(enrollment, actor=_actor(request))
    except services.AccessError:
        return HttpResponse('无权操作', status=403)
    except services.AcademicError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, '已退选')
    return redirect('/r5/sections/{}/roster/'.format(section.pk))


# ---------------------------------------------------------------------------
# R5-05 选课（学生视角）
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required('student', *TEACHER_ROLES)
def enroll_page(request):
    account = getattr(request, 'user', None)
    mine = services.student_sections(account).select_related('term', 'course')

    # 选课记录（用于退选按钮）
    enrollment_by_section = {
        e.section_id: e
        for e in Enrollment.objects.filter(
            account=account, status=Enrollment.STATUS_ENROLLED
        )
    }
    mine_rows = [
        {'section': section, 'enrollment': enrollment_by_section.get(section.pk)}
        for section in mine
    ]

    open_sections = TeachingSection.objects.filter(
        status=TeachingSection.STATUS_OPEN
    ).select_related('term', 'course').order_by('code')[:100]

    enrolled_ids = set(enrollment_by_section.keys())
    return render(request, 'r5/enroll.html', {
        'mine_rows': mine_rows,
        'open_sections': open_sections,
        'enrolled_ids': enrolled_ids,
    })


@require_POST
@roles_required('student', *TEACHER_ROLES)
def enroll_action(request, pk):
    section = TeachingSection.objects.filter(pk=pk).first()
    if section is None:
        return HttpResponse('教学班不存在', status=404)

    account = getattr(request, 'user', None)
    try:
        services.enroll(section, account, actor=_actor(request))
    except services.CapacityError:
        messages.error(request, '教学班容量已满，选课失败')
    except services.DuplicateError:
        messages.warning(request, '你已经选过该教学班')
    except services.AccessError:
        return HttpResponse('无权操作', status=403)
    except services.AcademicError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, '选课成功')

    return redirect('/r5/enroll/')


@require_POST
@roles_required('student', *TEACHER_ROLES)
def drop_action(request, pk):
    account = getattr(request, 'user', None)
    enrollment = Enrollment.objects.filter(
        pk=pk, account=account, status=Enrollment.STATUS_ENROLLED
    ).first()
    if enrollment is None:
        return HttpResponse('修读记录不存在', status=404)

    try:
        services.drop(enrollment, actor=_actor(request))
    except services.AcademicError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, '已退选')
    return redirect('/r5/enroll/')
