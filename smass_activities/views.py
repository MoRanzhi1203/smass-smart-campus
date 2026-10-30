"""R14 活动页面层：活动列表/详情、报名/取消/签到、学分认定。

权限原则
--------
- 所有页面要求登录；
- 创建/发布/关闭活动、生成与审批认定只对教师/管理员开放；
- 学生只能看已发布/已结束活动、自己的报名与认定；
- 业务校验全部在 ``services``。
"""
from __future__ import annotations

from datetime import datetime
from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import (
    CATEGORY_TYPES,
    STATUS_CLOSED,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    Activity,
    ActivityCredit,
    ActivityRegistration,
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
    return render(request, 'r14/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


def _parse_dt(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _aware(value):
    from django.utils import timezone
    if value is None:
        return None
    return timezone.make_aware(value)


# ---------------------------------------------------------------------------
# 活动
# ---------------------------------------------------------------------------
@require_GET
@require_login
def activity_list(request):
    can_manage = services.can_manage(request.user)
    activities = list(services.scoped_activities(request.user))
    rows = [{'activity': a, 'stats': services.activity_stats(a)} for a in activities]
    return render(request, 'r14/activities.html', {
        'rows': rows,
        'can_manage': can_manage,
        'categories': CATEGORY_TYPES,
        **_flash(request),
    })


@require_POST
@require_login
def activity_create(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    try:
        services.create_activity(
            request.user,
            request.POST.get('title', ''),
            (request.POST.get('category') or '').strip(),
            _aware(_parse_dt(request.POST.get('start_at'))),
            _aware(_parse_dt(request.POST.get('end_at'))),
            capacity=request.POST.get('capacity') or 0,
            credit_points=request.POST.get('credit_points') or 0,
            volunteer_hours=request.POST.get('volunteer_hours') or 0,
            location=request.POST.get('location', ''),
            deadline=_aware(_parse_dt(request.POST.get('registration_deadline'))),
        )
    except services.ActivityError as exc:
        return redirect('/r14/activities/?error={}'.format(quote(str(exc))))
    return redirect('/r14/activities/?ok={}'.format(quote('活动已创建（草稿）')))


@require_GET
@require_login
def activity_detail(request, pk):
    activity = get_object_or_404(Activity.objects.select_related('organizer'), pk=pk)
    can_manage = services.can_manage(request.user)
    if not can_manage and activity.status not in (STATUS_PUBLISHED, STATUS_CLOSED):
        return _forbidden(request, '该活动尚未发布')
    my_record = services.record_for_account(request.user)
    my_registration = None
    if my_record is not None:
        my_registration = ActivityRegistration.objects.filter(
            activity=activity, record=my_record).first()
    registrations = []
    if can_manage:
        registrations = list(activity.registrations.select_related('record').order_by(
            'status', 'registered_at'))
    return render(request, 'r14/activity_detail.html', {
        'activity': activity,
        'can_manage': can_manage,
        'my_record': my_record,
        'my_registration': my_registration,
        'registrations': registrations,
        'stats': services.activity_stats(activity),
        **_flash(request),
    })


@require_POST
@require_login
def activity_publish(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    activity = get_object_or_404(Activity, pk=pk)
    try:
        services.publish_activity(activity, request.user)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r14/activities/{}/?ok={}'.format(pk, quote('活动已发布')))


@require_POST
@require_login
def activity_close(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    activity = get_object_or_404(Activity, pk=pk)
    try:
        services.close_activity(activity, request.user)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r14/activities/{}/?ok={}'.format(pk, quote('活动已关闭')))


@require_POST
@require_login
def activity_generate_credits(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    activity = get_object_or_404(Activity, pk=pk)
    try:
        count = services.generate_credits(activity, request.user)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r14/activities/{}/?ok={}'.format(
        pk, quote('已生成 {} 条待认定记录'.format(count))))


# ---------------------------------------------------------------------------
# 报名与签到
# ---------------------------------------------------------------------------
@require_POST
@require_login
def activity_register(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    record = services.record_for_account(request.user)
    try:
        registration = services.register(activity, record, request.user)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(pk, quote(str(exc))))
    message = '报名成功' if registration.status == 'registered' else '已进入候补'
    return redirect('/r14/activities/{}/?ok={}'.format(pk, quote(message)))


@require_POST
@require_login
def registration_cancel(request, pk):
    registration = get_object_or_404(ActivityRegistration, pk=pk)
    try:
        services.cancel_registration(registration, request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(
            registration.activity_id, quote(str(exc))))
    return redirect('/r14/activities/{}/?ok={}'.format(
        registration.activity_id, quote('已取消报名')))


@require_POST
@require_login
def activity_check_in(request, pk):
    registration = get_object_or_404(ActivityRegistration, pk=pk)
    try:
        services.check_in(registration, request.user, request.POST.get('code', ''))
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ActivityError as exc:
        return redirect('/r14/activities/{}/?error={}'.format(
            registration.activity_id, quote(str(exc))))
    return redirect('/r14/activities/{}/?ok={}'.format(
        registration.activity_id, quote('签到成功')))


# ---------------------------------------------------------------------------
# 学分认定
# ---------------------------------------------------------------------------
@require_GET
@require_login
def credit_list(request):
    can_manage = services.can_manage(request.user)
    credits = list(services.scoped_credits(request.user))
    my_record = services.record_for_account(request.user)
    summary = services.credit_summary(my_record) if my_record else None
    return render(request, 'r14/credits.html', {
        'credits': credits,
        'can_manage': can_manage,
        'summary': summary,
        **_flash(request),
    })


@require_POST
@require_login
def credit_action(request, pk, action):
    credit = get_object_or_404(ActivityCredit, pk=pk)
    try:
        if action == 'approve':
            services.approve_credit(credit, request.user)
        elif action == 'reject':
            services.reject_credit(credit, request.user, request.POST.get('reason', ''))
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ActivityError as exc:
        return redirect('/r14/credits/?error={}'.format(quote(str(exc))))
    return redirect('/r14/credits/?ok={}'.format(quote('操作成功')))
