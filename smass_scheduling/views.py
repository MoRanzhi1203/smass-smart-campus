"""R11 排课与课表的页面/接口层。

页面（浏览器可见）：
- ``/r11/plan/``                 教务规划：批次列表、运行求解、查看冲突
- ``/r11/timetable/student/``    学生课表
- ``/r11/timetable/teacher/``    教师课表
- ``/r11/timetable/room/<pk>/``  教室课表

接口（JSON）：
- ``POST /r11/plan/<run_id>/solve/``   运行求解
- ``POST /r11/plan/<run_id>/publish/`` 发布（需 update 权限）
- ``GET  /r11/plan/<run_id>/conflicts/`` 冲突列表

权限：所有端点要求登录；运行求解需 ``create``，发布需 ``update``；
学生只能看自己的课表，教师只能看自己的课表，管理员可看任意教室课表。
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from r21_account import authorization as authz
from r21_account.models import RoleCode

from . import solver
from .models import (
    RUN_INFEASIBLE,
    RUN_PUBLISHED,
    RUN_SOLVED,
    ScheduleEntry,
    ScheduleRun,
    TimeSlot,
)

#: 课表表格的节次上限（用于渲染矩阵）
MAX_PERIOD_COLUMNS = 12
WEEKDAY_LABELS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def _login_url():
    return getattr(settings, 'LOGIN_URL', '/r21/login/')


def require_login(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_authenticated', False):
            target = request.get_full_path()
            return redirect('{}?next={}'.format(_login_url(), quote(target)))
        return view(request, *args, **kwargs)

    return _wrapped


def _wants_json(request):
    return (request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', ''))


def _roles(account):
    return authz.active_roles(account)


def _is_admin(account):
    return bool(_roles(account) & {RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})


# ---------------------------------------------------------------------------
# 课表矩阵
# ---------------------------------------------------------------------------
def _grid(entries, periods=None, days=7):
    """把 entries 组织成 ``grid[weekday][period] = [entry...]``。"""
    grid = [[[] for _ in range(periods or MAX_PERIOD_COLUMNS)] for _ in range(days)]
    for e in entries:
        wd = int(e.weekday)
        pd = int(e.period)
        if 0 <= wd < days and 0 < pd <= (periods or MAX_PERIOD_COLUMNS):
            grid[wd][pd - 1].append(e)
    return grid


def _slots_map():
    return {(s.weekday, s.period): s for s in TimeSlot.objects.all()}


def _cell_render(entry, slots):
    slot = slots.get((entry.weekday, entry.period))
    time_label = ''
    if slot:
        time_label = '{} - {}'.format(
            slot.start_time.strftime('%H:%M'), slot.end_time.strftime('%H:%M'))
    return {
        'entry': entry,
        'time_label': time_label,
        'course': getattr(entry.requirement.section.course, 'title', ''),
        'section': entry.requirement.section.code,
        'teacher': getattr(entry.teacher, 'display_name', '') or str(entry.teacher_id),
        'room': entry.room.code,
        'cohort': entry.cohort.name,
    }


# ---------------------------------------------------------------------------
# 页面：教务规划
# ---------------------------------------------------------------------------
@require_GET
@require_login
def plan_page(request):
    if not _is_admin(request.user):
        return render(request, 'r11/forbidden.html', status=403)

    runs = list(
        ScheduleRun.objects.select_related('term', 'term__year')
        .order_by('-created_at')[:50])
    selected_id = request.GET.get('run')
    selected = None
    if selected_id:
        selected = ScheduleRun.objects.filter(pk=selected_id).first()
    if selected is None and runs:
        selected = runs[0]

    conflicts = []
    entries = []
    if selected is not None:
        conflicts = list(selected.conflicts.select_related('requirement')[:200])
        entries = list(
            selected.entries.select_related(
                'requirement', 'requirement__section',
                'requirement__section__course', 'room', 'teacher', 'cohort'))

    slots = _slots_map()
    return render(request, 'r11/plan.html', {
        'runs': runs,
        'selected': selected,
        'conflicts': conflicts,
        'entries': entries,
        'entry_count': len(entries),
        'slots': slots,
        'weekday_labels': WEEKDAY_LABELS,
        'can_solve': authz.has_action(request.user, 'create'),
        'can_publish': authz.has_action(request.user, 'update'),
    })


@require_POST
@require_login
def plan_solve(request, run_id):
    if not authz.has_action(request.user, 'create'):
        return JsonResponse({'ok': False, 'error': '没有运行排课的权限'}, status=403)
    run = get_object_or_404(ScheduleRun, pk=run_id)
    if run.status == RUN_PUBLISHED:
        return JsonResponse({'ok': False, 'error': '已发布的批次不能重新求解'},
                            status=400)

    result = solver.solve(run)
    run.refresh_from_db()
    payload = {
        'ok': True,
        'feasible': result.feasible,
        'placed': result.placed,
        'required': result.required,
        'hard_conflicts': result.hard_conflicts,
        'soft_cost': result.soft_cost,
        'status': run.status,
        'explanation': result.explanation,
    }
    return JsonResponse(payload)


@require_POST
@require_login
def plan_publish(request, run_id):
    if not authz.has_action(request.user, 'update'):
        return JsonResponse({'ok': False, 'error': '没有发布权限'}, status=403)
    run = get_object_or_404(ScheduleRun, pk=run_id)
    if run.status != RUN_SOLVED:
        return JsonResponse(
            {'ok': False, 'error': '只有已求解且无硬冲突的批次可以发布（当前：{}）'.format(
                run.status)}, status=400)
    if run.hard_conflicts:
        return JsonResponse(
            {'ok': False, 'error': '存在硬冲突（{}），不能发布'.format(run.hard_conflicts)},
            status=400)

    # 发布前独立复核，避免把有问题的批次发出去
    problems = solver.verify_run(run)
    if problems:
        return JsonResponse(
            {'ok': False, 'error': '发布前复核未通过', 'problems': problems[:20]},
            status=400)

    run.status = RUN_PUBLISHED
    run.published_at = timezone.now()
    run.save(update_fields=['status', 'published_at'])
    return JsonResponse({'ok': True, 'status': run.status,
                         'published_at': run.published_at.isoformat()})


@require_GET
@require_login
def plan_conflicts(request, run_id):
    if not _is_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    run = get_object_or_404(ScheduleRun, pk=run_id)
    rows = [{
        'kind': c.kind,
        'requirement': c.requirement_id,
        'section': (str(c.requirement.section_id) if c.requirement_id else ''),
        'weekday': c.weekday,
        'period': c.period,
        'detail': c.detail,
    } for c in run.conflicts.select_related('requirement')[:500]]
    return JsonResponse({'ok': True, 'run': run.pk, 'status': run.status,
                         'explanation': run.explanation, 'conflicts': rows})


# ---------------------------------------------------------------------------
# 页面：三张课表
# ---------------------------------------------------------------------------
def _published_runs():
    return ScheduleRun.objects.filter(status=RUN_PUBLISHED).order_by('-published_at')


def _pick_run(request):
    run_id = request.GET.get('run')
    if run_id:
        return ScheduleRun.objects.filter(pk=run_id, status=RUN_PUBLISHED).first()
    return _published_runs().first()


@require_GET
@require_login
def student_timetable(request):
    run = _pick_run(request)
    entries = []
    if run is not None:
        from smass_academic.models import Enrollment

        sections = Enrollment.objects.filter(
            account=request.user).exclude(status='dropped').values_list(
            'section_id', flat=True)
        entries = list(
            ScheduleEntry.objects.filter(run=run, requirement__section_id__in=sections)
            .select_related('requirement', 'requirement__section',
                            'requirement__section__course', 'room', 'teacher', 'cohort')
            .order_by('weekday', 'period'))
    return _render_timetable(request, 'r11/timetable.html', run, entries,
                             title='我的课表')


@require_GET
@require_login
def teacher_timetable(request):
    run = _pick_run(request)
    entries = []
    if run is not None:
        entries = list(
            ScheduleEntry.objects.filter(run=run, teacher=request.user)
            .select_related('requirement', 'requirement__section',
                            'requirement__section__course', 'room', 'teacher', 'cohort')
            .order_by('weekday', 'period'))
    return _render_timetable(request, 'r11/timetable.html', run, entries,
                             title='我的课表（教师）')


@require_GET
@require_login
def room_timetable(request, room_id):
    from smass_facilities.models import Room

    room = get_object_or_404(Room, pk=room_id)
    if not _is_admin(request.user):
        return render(request, 'r11/forbidden.html', status=403)

    run = _pick_run(request)
    entries = []
    if run is not None:
        entries = list(
            ScheduleEntry.objects.filter(run=run, room=room)
            .select_related('requirement', 'requirement__section',
                            'requirement__section__course', 'room', 'teacher', 'cohort')
            .order_by('weekday', 'period'))
    response = _render_timetable(request, 'r11/timetable.html', run, entries,
                                title='教室课表 {}'.format(room.code))
    return response


def _render_timetable(request, template, run, entries, *, title):
    slots = _slots_map()
    grid = _grid(entries, periods=MAX_PERIOD_COLUMNS, days=7)
    rendered = [
        [
            [_cell_render(e, slots) for e in cell]
            for cell in row
        ]
        for row in grid
    ]
    periods = sorted({e.period for e in entries}) or list(range(1, 6))
    return render(request, template, {
        'title': title,
        'run': run,
        'runs': _published_runs()[:10],
        'entry_count': len(entries),
        'grid': rendered,
        'periods': periods,
        'weekday_labels': WEEKDAY_LABELS,
        'has_data': bool(entries),
    })


# ---------------------------------------------------------------------------
# 接口：我的课表 JSON（便于手机端/前端复用）
# ---------------------------------------------------------------------------
@require_GET
@require_login
def my_timetable_json(request):
    run = _pick_run(request)
    if run is None:
        return JsonResponse({'ok': True, 'run': None, 'entries': []})

    roles = _roles(request.user)
    if RoleCode.TEACHER in roles and RoleCode.STUDENT not in roles:
        qs = ScheduleEntry.objects.filter(run=run, teacher=request.user)
    else:
        from smass_academic.models import Enrollment

        sections = Enrollment.objects.filter(
            account=request.user).exclude(status='dropped').values_list(
            'section_id', flat=True)
        qs = ScheduleEntry.objects.filter(run=run,
                                          requirement__section_id__in=sections)

    entries = [{
        'weekday': e.weekday,
        'period': e.period,
        'course': getattr(e.requirement.section.course, 'title', ''),
        'section': e.requirement.section.code,
        'teacher': getattr(e.teacher, 'display_name', ''),
        'room': e.room.code,
        'cohort': e.cohort.name,
    } for e in qs.select_related(
        'requirement', 'requirement__section', 'requirement__section__course',
        'room', 'teacher', 'cohort').order_by('weekday', 'period')]

    return JsonResponse({'ok': True, 'run': run.pk,
                         'published_at': (run.published_at.isoformat()
                                          if run.published_at else None),
                         'entries': entries})
