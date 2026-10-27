"""R2.1 最小认证视图：登录 / 注销 / 首页 / 强制改密 / 受保护探针。"""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from r21_account.services import (
    login_lock_status,
    password_policy_errors,
    register_login_result,
)


def _client_ip(request):
    return request.META.get('REMOTE_ADDR', '') or ''


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('/r21/home/')

    error = None
    status = 200

    if request.method == 'POST':
        login_name = (request.POST.get('login_name') or '').strip()
        password = request.POST.get('password') or ''
        ip = _client_ip(request)

        # 持久化限速：登录前先查锁定状态（跨会话有效）
        locked, remaining, reason = login_lock_status(login_name, ip)
        if locked:
            error = '登录失败次数过多，请 {} 秒后再试'.format(remaining)
            return render(
                request, 'r21/login.html', {'error': error, 'locked': True}, status=429
            )

        account = authenticate(request, username=login_name, password=password)
        if account is not None:
            register_login_result(login_name, ip, success=True)
            login(request, account)
            return redirect('/r21/home/')

        register_login_result(login_name, ip, success=False)
        # 统一错误信息，避免账号枚举
        error = '账号或密码错误，或账号已停用'

    return render(request, 'r21/login.html', {'error': error}, status=status)


def logout_view(request):
    logout(request)
    return redirect('/r21/login/')


def home_view(request):
    if not request.user.is_authenticated:
        return redirect('/r21/login/')

    account = request.user
    return render(request, 'r21/home.html', {
        'account': account,
        'roles': account.active_roles(),
        'must_change': account.must_change_password,
    })


def ping_view(request):
    """受保护探针：用于验证登录态与 RBAC 拒绝。"""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'reason': 'anonymous'}, status=403)
    return JsonResponse({
        'ok': True,
        'login_name': request.user.login_name,
        'roles': request.user.active_roles(),
    })


@require_http_methods(['GET', 'POST'])
def change_password_view(request):
    """强制改密 / 主动改密（三端共用）。"""
    if not request.user.is_authenticated:
        return redirect('/r21/login/')

    account = request.user
    errors = []
    done = False

    if request.method == 'POST':
        current = request.POST.get('current_password') or ''
        new_password = request.POST.get('new_password') or ''
        confirm = request.POST.get('confirm_password') or ''

        if not account.check_password(current):
            errors.append('当前密码不正确')
        elif new_password != confirm:
            errors.append('两次输入的新密码不一致')
        elif current == new_password:
            errors.append('新密码不能与当前密码相同')
        else:
            policy = password_policy_errors(new_password, account)
            if policy:
                errors.extend(policy)
            else:
                account.set_password(new_password)
                account.must_change_password = False
                account.save(update_fields=[
                    'password', 'must_change_password', 'password_changed_at',
                ])
                # 密码变更后刷新会话哈希，避免被立即登出
                update_session_auth_hash(request, account)
                done = True

    return render(request, 'r21/change_password.html', {
        'account': account,
        'errors': errors,
        'done': done,
        'forced': account.must_change_password,
    })
