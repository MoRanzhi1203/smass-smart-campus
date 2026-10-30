"""S09 页面层：MFA 绑定、二次验证与状态管理。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from . import services


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


def _next_url(request, default='/s09/status/'):
    target = request.POST.get('next') or request.GET.get('next') or default
    if not str(target).startswith('/') or str(target).startswith('//'):
        return default
    return target


@require_http_methods(['GET', 'POST'])
@require_login
def setup(request):
    state = services.device_status(request.user)
    if state['active']:
        return redirect('/s09/status/')

    if request.method == 'GET':
        device, uri = services.enroll(request.user)
        return render(request, 's09/setup.html', {
            'secret': device.secret,
            'uri': uri,
            'next': _next_url(request),
            **_flash(request),
        })

    try:
        codes = services.confirm(request.user, request.POST.get('code', ''))
    except services.MfaError as exc:
        return redirect('/s09/setup/?error={}&next={}'.format(
            quote(str(exc)), quote(_next_url(request))))
    services.mark_session_verified(request.session)
    return render(request, 's09/recovery.html', {
        'codes': codes,
        'next': _next_url(request),
    })


@require_http_methods(['GET', 'POST'])
@require_login
def verify(request):
    if request.method == 'GET':
        return render(request, 's09/verify.html', {
            'next': _next_url(request),
            **_flash(request),
        })

    try:
        method = services.verify(request.user, request.POST.get('code', ''))
    except services.MfaError as exc:
        return redirect('/s09/verify/?error={}&next={}'.format(
            quote(str(exc)), quote(_next_url(request))))
    services.mark_session_verified(request.session)
    request.session['mfa_method'] = method
    return redirect(_next_url(request))


@require_GET
@require_login
def status(request):
    return render(request, 's09/status.html', {
        'state': services.device_status(request.user),
        'privileged': services.is_privileged(request.user),
        'enabled': services.mfa_enabled(),
        'verified': services.session_verified(request.session),
        **_flash(request),
    })


@require_POST
@require_login
def disable(request):
    try:
        services.disable(request.user, request.POST.get('code', ''))
    except services.MfaError as exc:
        return redirect('/s09/status/?error={}'.format(quote(str(exc))))
    services.clear_session_verified(request.session)
    return redirect('/s09/status/?ok={}'.format(quote('MFA 已停用')))


@require_POST
@require_login
def regenerate(request):
    try:
        codes = services.regenerate_recovery_codes(
            request.user, request.POST.get('code', ''))
    except services.MfaError as exc:
        return redirect('/s09/status/?error={}'.format(quote(str(exc))))
    return render(request, 's09/recovery.html', {
        'codes': codes,
        'next': '/s09/status/',
    })
