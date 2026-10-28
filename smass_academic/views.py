"""R5 视图：学年/学期/课程/教学班/任课/修读 + 三端页面。"""
import json
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

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
ANY_ROLES = {'system_admin', 'college_admin', 'teacher', 'student'}


def _body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def _date(value):
    from datetime import date

    if not value:
        raise services.DateRangeError('日期不能为空')
    return date.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# R5-01 学年 / 学期
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*ACADEMIC_ROLES)
def year_list(request):
    years = AcademicYear.objects.all().order_by('-start_date')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'code': y.code, 'start': str(y.start_date), 'end': str(y.end_date),
             'is_active': y.is_active} for y in years
        ]})
    return render(request, 'r5/year_list.html', {'years': years})


@require_POST
@roles_required(*ADMIN_ROLES)
def year_create(request):
    data = _body(request)
    try:
        year = services.create_year(
            data.get('code', ''),
            _date(data.get('start_date')),
            _date(data.get('end_date')),
            is_active=bool(data.get('is_active')),
        )
    except services.AcademicError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': year.pk, 'code': year.code})


@require_POST
@roles_required(*ADMIN_ROLES)
def year_activate(request, pk):
    year = AcademicYear.objects.filter(pk=pk).first()
    if year is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)
    services.activate_year(year)
    return JsonResponse({'ok': True})


@require_http_methods(['GET'])
@roles_required(*ACADEMIC_ROLES)
def term_list(request):
    terms = AcademicTerm.objects.select_related('year').order_by('-start_date')
    return render(request, 'r5/term_list.html', {'terms': terms})


@require_POST
@roles_required(*ADMIN_ROLES)
def term_create(request):
    data = _body(request)
    year = AcademicYear.objects.filter(pk=data.get('year')).first()
    if year is None:
        return JsonResponse({'ok': False, 'reason': '学年不存在'}, status=400)

    try:
        term = services.create_term(
            year, data.get('semester', '1'),
            _date(data.get('start_date')), _date(data.get('end_date')),
            name=data.get('name', ''), is_active=bool(data.get('is_active')),
        )
    except services.AcademicError as exc:
        code = 'DATE_RANGE' if isinstance(exc, services.DateRangeError) else 'DUPLICATE'
        return JsonResponse({'ok': False, 'code': code, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': term.pk})


# ---------------------------------------------------------------------------
# R5-02 课程
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*ACADEMIC_ROLES)
def course_list(request):
    keyword = request.GET.get('q')
    active_only = request.GET.get('active') == '1'
    courses = services.search_courses(keyword, active_only)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'code': c.code, 'title': c.title,
             'credit': str(c.credit) if c.credit is not None else '',
             'type': c.course_type, 'is_active': c.is_active}
            for c in courses[:200]
        ]})
    return render(request, 'r5/course_list.html', {'courses': courses[:200]})


@require_POST
@roles_required(*ADMIN_ROLES)
def course_create(request):
    data = _body(request)
    try:
        credit = Decimal(str(data['credit'])) if data.get('credit') not in (None, '') else None
    except (InvalidOperation, KeyError):
        return JsonResponse({'ok': False, 'reason': '学分格式非法'}, status=400)

    try:
        course = services.create_course(
            data.get('code', ''), data.get('title', ''),
            credit=credit, course_type=data.get('course_type', ''),
            is_active=bool(data.get('is_active', True)),
        )
    except services.AcademicError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': course.pk, 'code': course.code})


# ---------------------------------------------------------------------------
# R5-03 教学班
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*ACADEMIC_ROLES)
def section_list(request):
    sections = TeachingSection.objects.select_related('term', 'course').order_by('code')
    return render(request, 'r5/section_list.html', {'sections': sections[:200]})


@require_POST
@roles_required(*ADMIN_ROLES)
def section_create(request):
    data = _body(request)
    term = AcademicTerm.objects.filter(pk=data.get('term')).first()
    course = Course.objects.filter(pk=data.get('course')).first()
    if term is None or course is None:
        return JsonResponse({'ok': False, 'reason': '学期或课程不存在'}, status=400)

    try:
        section = services.create_section(
            term, course, data.get('code', ''), capacity=int(data.get('capacity') or 0)
        )
    except services.AcademicError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': section.pk})


# ---------------------------------------------------------------------------
# R5-04 教师工作台
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def teacher_workspace(request):
    account = getattr(request, 'user', None)
    sections = services.teacher_sections(account)
    rows = []
    for section in sections.select_related('term', 'course'):
        rows.append({
            'id': section.pk, 'code': section.code,
            'course': section.course.title, 'term': str(section.term),
            'enrolled': Enrollment.objects.filter(
                section=section, status=Enrollment.STATUS_ENROLLED
            ).count(),
        })
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'sections': rows})
    return render(request, 'r5/teacher_workspace.html', {'sections': rows})


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def section_roster(request, pk):
    account = getattr(request, 'user', None)
    section = TeachingSection.objects.filter(pk=pk).first()
    if section is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    try:
        roster = services.section_roster(section, account)
    except services.AccessError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=403)

    return JsonResponse({'ok': True, 'section': section.code, 'rows': [
        {'student': e.account.login_name, 'status': e.status} for e in roster[:200]
    ]})


# ---------------------------------------------------------------------------
# R5-05 学生自己的课程
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*ANY_ROLES)
def my_sections(request):
    account = getattr(request, 'user', None)
    sections = services.student_sections(account)
    rows = [
        {'id': s.pk, 'code': s.code, 'course': s.course.title, 'term': str(s.term)}
        for s in sections.select_related('term', 'course')
    ]
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'sections': rows})
    return render(request, 'r5/my_sections.html', {'sections': rows})


def health(request):
    return JsonResponse({
        'ok': True,
        'module': 'smass_academic',
        'years': AcademicYear.objects.count(),
        'terms': AcademicTerm.objects.count(),
        'courses': Course.objects.count(),
        'sections': TeachingSection.objects.count(),
    })
