"""统一入口：登录、退出、按角色落地。

全系统只有一个登录入口 ``/login/``；登录成功后由后端按角色计算落地工作台，
不接受前端传入的"角色"参数（避免越权选择）。
"""
from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from r21_account.services import login_lock_status, register_login_result

from .. import permissions as perms


def _client_ip(request) -> str:
    return request.META.get('REMOTE_ADDR', '') or ''


def _safe_next(request):
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    if candidate and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        return candidate
    return ''


@require_http_methods(['GET', 'POST'])
def login_view(request):
    account = getattr(request, 'user', None)
    if perms.is_authenticated(account):
        return redirect(perms.landing_url(account))

    error = ''
    status = 200

    if request.method == 'POST':
        login_name = (request.POST.get('login_name') or '').strip()
        password = request.POST.get('password') or ''
        ip = _client_ip(request)

        locked, remaining, _reason = login_lock_status(login_name, ip)
        if locked:
            error = '登录失败次数过多，请 {} 秒后再试'.format(remaining)
            status = 429
        else:
            account = authenticate(request, username=login_name, password=password)
            if account is not None:
                register_login_result(login_name, ip, success=True)
                login(request, account)
                target = _safe_next(request)
                if target:
                    return redirect(target)
                kind = perms.landing_kind(account)
                if kind is None:
                    return redirect(reverse('workspace:no_role'))
                return redirect(reverse('workspace:{}_home'.format(kind)))
            register_login_result(login_name, ip, success=False)
            error = '账号或密码错误，或账号已停用'

    return render(request, 'workspace/login.html', {
        'error': error,
        'next': _safe_next(request),
        'login_name': (request.POST.get('login_name') or '').strip(),
    }, status=status)


@require_POST
def logout_view(request):
    logout(request)
    return redirect(reverse('workspace:login'))


def root_view(request):
    """站点根路径：未登录去登录页，已登录去本角色工作台。"""
    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect(reverse('workspace:login'))
    return redirect(perms.landing_url(account))
