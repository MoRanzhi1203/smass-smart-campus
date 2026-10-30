"""R13 考勤页面层：会话、签到、请假销假、补签与统计。

权限原则
--------
- 所有页面要求登录；
- 创建/关闭会话、手动标记、审批请假与补签只对教师/管理员开放；
- 学生只能看到自己班级的会话、自己的请假与补签；
- 所有业务校验在 ``services``，视图只做参数解析与渲染。
"""
from __future__ import annotations

from datetime import datetime
from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from smass_organization.models import StudentRecord

from . import services
from .models import (
    LEAVE_TYPES,
    RECORD_STATUS,
    AttendanceSession,
    LeaveRequest,
    MakeupRequest,
)


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


def _forbidden(request, message='当前账号没有访问该页面的权限'):
    return render(request, 'r13/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


def _classes():
    from smass_organization.models import OrganizationUnit
    return OrganizationUnit.objects.filter(
        unit_type='class', status='active').order_by('code')


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 考勤会话
# ---------------------------------------------------------------------------
@require_GET
@require_login
def session_list(request):
    can_manage = services.can_manage(request.user)
    sessions = list(services.scoped_sessions(request.user).order_by(
        '-session_date', 'period')[:50])
    rows = [{'session': s, 'stats': services.session_stats(s)} for s in sessions]
    return render(request, 'r13/sessions.html', {
        'rows': rows,
        'can_manage': can_manage,
        'classes': list(_classes()) if can_manage else [],
        'today': timezone.localdate().isoformat(),
        **_flash(request),
    })


@require_POST
@require_login
def session_create(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    from smass_organization.models import OrganizationUnit
    unit = OrganizationUnit.objects.filter(
        pk=request.POST.get('unit') or 0, unit_type='class').first()
    day = _parse_date(request.POST.get('session_date'))
    period = (request.POST.get('period') or '').strip() or '第1-2节'
    try:
        services.create_session(
            unit, day, period, request.user,
            topic=request.POST.get('topic', ''))
    except services.AttendanceError as exc:
        return redirect('/r13/sessions/?error={}'.format(quote(str(exc))))
    return redirect('/r13/sessions/?ok={}'.format(quote('考勤会话已创建')))


@require_GET
@require_login
def session_detail(request, pk):
    session = get_object_or_404(
        AttendanceSession.objects.select_related('unit'), pk=pk)
    if not services.can_manage(request.user):
        record = services.record_for_account(request.user)
        if record is None or record.unit_id != session.unit_id:
            return _forbidden(request, '只能查看自己班级的考勤')
    records = list(session.records.select_related('record').order_by(
        'record__student_no'))
    return render(request, 'r13/session_detail.html', {
        'session': session,
        'records': records,
        'stats': services.session_stats(session),
        'can_manage': services.can_manage(request.user),
        'statuses': RECORD_STATUS,
        'my_record': services.record_for_account(request.user),
        **_flash(request),
    })


@require_POST
@require_login
def session_sign(request, pk):
    session = get_object_or_404(AttendanceSession, pk=pk)
    try:
        record, created = services.sign_in(
            session, request.user, request.POST.get('code', ''),
            ip=request.META.get('REMOTE_ADDR', ''))
    except services.AttendanceError as exc:
        return redirect('/r13/sessions/{}/?error={}'.format(pk, quote(str(exc))))
    message = '签到成功' if created else '已签到（重复提交不会重复记录）'
    return redirect('/r13/sessions/{}/?ok={}'.format(pk, quote(message)))


@require_POST
@require_login
def session_close(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    session = get_object_or_404(AttendanceSession, pk=pk)
    try:
        services.close_session(session, request.user)
    except services.AttendanceError as exc:
        return redirect('/r13/sessions/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r13/sessions/{}/?ok={}'.format(pk, quote('考勤已关闭')))


@require_POST
@require_login
def session_mark(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    session = get_object_or_404(AttendanceSession, pk=pk)
    student = StudentRecord.objects.filter(
        pk=_parse_pk(request.POST.get('record'))).first()
    try:
        services.teacher_mark(
            session, student, request.POST.get('status', ''), request.user,
            note=request.POST.get('note', ''))
    except services.AttendanceError as exc:
        return redirect('/r13/sessions/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r13/sessions/{}/?ok={}'.format(pk, quote('已更新考勤')))


# ---------------------------------------------------------------------------
# 请假
# ---------------------------------------------------------------------------
@require_GET
@require_login
def leave_list(request):
    can_manage = services.can_manage(request.user)
    leaves = list(services.scoped_leaves(request.user).order_by('-created_at')[:100])
    return render(request, 'r13/leaves.html', {
        'leaves': leaves,
        'can_manage': can_manage,
        'leave_types': LEAVE_TYPES,
        'my_record': services.record_for_account(request.user),
        **_flash(request),
    })


@require_POST
@require_login
def leave_submit(request):
    record_id = (request.POST.get('record_id') or '').strip()
    if services.can_manage(request.user) and record_id:
        record = StudentRecord.objects.filter(pk=record_id).first()
    else:
        record = services.record_for_account(request.user)
    try:
        services.submit_leave(
            record, (request.POST.get('leave_type') or '').strip(),
            _parse_date(request.POST.get('start_date')),
            _parse_date(request.POST.get('end_date')),
            request.POST.get('reason', ''), request.user)
    except services.AttendanceError as exc:
        return redirect('/r13/leaves/?error={}'.format(quote(str(exc))))
    return redirect('/r13/leaves/?ok={}'.format(quote('请假申请已提交')))


@require_POST
@require_login
def leave_action(request, pk, action):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_leave(leave, request.user)
        elif action == 'reject':
            services.reject_leave(leave, request.user, request.POST.get('reason', ''))
        elif action == 'cancel':
            services.cancel_leave(leave, request.user)
        elif action == 'close':
            services.close_leave(leave, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.AttendanceError as exc:
        return redirect('/r13/leaves/?error={}'.format(quote(str(exc))))
    return redirect('/r13/leaves/?ok={}'.format(quote('操作成功')))


# ---------------------------------------------------------------------------
# 补签
# ---------------------------------------------------------------------------
@require_GET
@require_login
def makeup_list(request):
    can_manage = services.can_manage(request.user)
    makeups = list(services.scoped_makeups(request.user).order_by('-created_at')[:100])
    my_record = services.record_for_account(request.user)
    closed_sessions = []
    if my_record is not None:
        closed_sessions = list(AttendanceSession.objects.filter(
            unit=my_record.unit, status='closed').order_by('-session_date')[:30])
    return render(request, 'r13/makeups.html', {
        'makeups': makeups,
        'can_manage': can_manage,
        'my_record': my_record,
        'closed_sessions': closed_sessions,
        **_flash(request),
    })


@require_POST
@require_login
def makeup_submit(request):
    record_id = (request.POST.get('record_id') or '').strip()
    if services.can_manage(request.user) and record_id:
        record = StudentRecord.objects.filter(pk=record_id).first()
    else:
        record = services.record_for_account(request.user)
    session = AttendanceSession.objects.filter(
        pk=_parse_pk(request.POST.get('session'))).first()
    try:
        services.submit_makeup(record, session, request.POST.get('reason', ''), request.user)
    except services.AttendanceError as exc:
        return redirect('/r13/makeups/?error={}'.format(quote(str(exc))))
    return redirect('/r13/makeups/?ok={}'.format(quote('补签申请已提交')))


@require_POST
@require_login
def makeup_action(request, pk, action):
    makeup = get_object_or_404(MakeupRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_makeup(makeup, request.user)
        elif action == 'reject':
            services.reject_makeup(makeup, request.user, request.POST.get('reason', ''))
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.AttendanceError as exc:
        return redirect('/r13/makeups/?error={}'.format(quote(str(exc))))
    return redirect('/r13/makeups/?ok={}'.format(quote('操作成功')))


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
@require_GET
@require_login
def stats_view(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    from smass_organization.models import OrganizationUnit
    unit_id = _parse_pk(request.GET.get('unit'))
    unit = OrganizationUnit.objects.filter(
        pk=unit_id, unit_type='class').first() if unit_id else _classes().first()
    rows = services.unit_stats(unit) if unit else []
    return render(request, 'r13/stats.html', {
        'unit': unit,
        'rows': rows,
        'classes': list(_classes()),
        **_flash(request),
    })


def _parse_pk(raw):
    """把请求参数转成合法主键；非法值返回 None，避免 ValueError 变成 500。"""
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None
