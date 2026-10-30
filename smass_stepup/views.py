"""S10 页面层：再认证、双人审批工单与执行。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import DualApproval, METHODS

SENSITIVE_ACTIONS = services.SENSITIVE_ACTIONS


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


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


def _next_url(request, default='/s10/approvals/'):
    target = request.POST.get('next') or request.GET.get('next') or default
    if not str(target).startswith('/') or str(target).startswith('//'):
        return default
    return target


@require_GET
@require_login
def index(request):
    actions = []
    for item in services.action_catalog():
        actions.append(dict(item, verified=services.has_stepup(
            request.user, item['code'])))
    return render(request, 's10/index.html', {
        'actions': actions,
        'can_approve': services.can_approve(request.user),
        **_flash(request),
    })


@require_GET
@require_login
def verify_page(request):
    return render(request, 's10/verify.html', {
        'actions': services.action_catalog(),
        'methods': METHODS,
        'action_code': request.GET.get('action', ''),
        'next': _next_url(request),
        **_flash(request),
    })


@require_POST
@require_login
def verify_submit(request):
    try:
        services.verify_stepup(
            request.user,
            (request.POST.get('action_code') or '').strip(),
            request.POST.get('code', ''),
            method=(request.POST.get('method') or 'password').strip(),
            ip=request.META.get('REMOTE_ADDR', ''))
    except services.StepUpError as exc:
        return redirect('/s10/verify/?error={}&next={}'.format(
            quote(str(exc)), quote(_next_url(request))))
    return redirect('{}?ok={}'.format(
        _next_url(request), quote('再认证成功（5 分钟内有效）')))


@require_POST
@require_login
def approval_open(request):
    action_code = (request.POST.get('action_code') or '').strip()
    payload = {
        'target': (request.POST.get('target') or '').strip(),
        'note': (request.POST.get('note') or '').strip(),
    }
    try:
        approval = services.open_approval(
            request.user, action_code, payload, request.POST.get('reason', ''))
    except services.StepUpError as exc:
        if exc.code == 'STEPUP_REQUIRED':
            return redirect('/s10/verify/?action={}&next=/s10/approvals/'.format(
                quote(action_code)))
        return redirect('/s10/approvals/?error={}'.format(quote(str(exc))))
    return redirect('/s10/approvals/?ok={}'.format(
        quote('工单已创建（#{}）'.format(approval.pk))))


@require_GET
@require_login
def approval_list(request):
    services.expire_stale()
    approvals = list(services.scoped_approvals(request.user)[:100])
    return render(request, 's10/approvals.html', {
        'approvals': approvals,
        'can_approve': services.can_approve(request.user),
        'logs': list(services.scoped_operation_logs(request.user)[:20]),
        **_flash(request),
    })


@require_POST
@require_login
def approval_action(request, pk, action):
    approval = get_object_or_404(DualApproval, pk=pk)
    try:
        if action == 'approve':
            services.approve_approval(approval, request.user)
        elif action == 'reject':
            services.reject_approval(approval, request.user,
                                     request.POST.get('reason', ''))
        elif action == 'execute':
            services.execute_approval(approval, request.user)
        else:
            return render(request, 's10/forbidden.html',
                          {'message': '未知操作'}, status=403)
    except services.PermissionDenied:
        return render(request, 's10/forbidden.html',
                      {'message': '当前账号没有该操作权限'}, status=403)
    except services.StepUpError as exc:
        return redirect('/s10/approvals/?error={}'.format(quote(str(exc))))
    return redirect('/s10/approvals/?ok={}'.format(quote('操作成功')))
