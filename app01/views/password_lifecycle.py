"""S02 密码生命周期视图。

对外提供两个入口：

1. ``/account/password/forced/`` —— 首次登录 / 临时口令登录后的**强制改密**页。
   登录态即可访问（三种角色共用），改密成功后清除强制标记并把当前会话
   切换到新世代（不会把自己踢下线），其余旧会话仍全部失效。

2. ``/admin/admin/temp-password/`` —— 管理员为指定账号发放**一次性临时口令**。
   明文只在响应里出现一次，不入日志、不入库；同时置强制改密与到期时间，
   并让该账号所有旧会话失效。

权限：沿用 ``app01.utils.authz.role_required``，不做角色降级重定向。
"""
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from app01 import models
from app01.services import accounts
from app01.services import password_lifecycle as lifecycle
from app01.utils.authz import role_required

#: 角色 -> 账号模型（与 accounts.ROLE_* 对齐）
ACCOUNT_MODELS = {
    accounts.ROLE_ADMIN: models.Admin,
    accounts.ROLE_STUDENT: models.Student,
    accounts.ROLE_TEACHER: models.Teacher,
}


def _session_account(request):
    """从服务端会话解析当前账号（不信任任何请求参数）。"""
    info = request.session.get('info') or {}
    account_type = info.get('type')
    account_id = info.get('id')
    model = ACCOUNT_MODELS.get(account_type)
    if model is None or not account_id:
        return None, None, None
    return account_type, account_id, model.objects.filter(pk=account_id).first()


def _render(request, errors=None, notice=None):
    account_type, _aid, account = _session_account(request)
    state = lifecycle.get_state(account_type, account.pk) if account else None
    return render(request, 'account/password-forced.html', {
        'errors': errors or [],
        'notice': notice,
        'role': account_type,
        'role_label': accounts.ROLE_LABELS.get(account_type, ''),
        'account_name': getattr(account, 'name', '') if account else '',
        'state': state,
        'policy': lifecycle.policy(),
        'lifecycle_enabled': lifecycle.lifecycle_enabled(),
        'home_url': accounts.ROLE_HOME_URLS.get(account_type, '/'),
    })


@role_required(accounts.ROLE_ADMIN, accounts.ROLE_STUDENT, accounts.ROLE_TEACHER)
@require_http_methods(['GET', 'POST'])
def password_forced_change(request):
    """强制改密页（首次登录 / 临时口令后）。"""
    account_type, _aid, account = _session_account(request)
    if account is None:
        return redirect('/login/')

    if request.method == 'GET':
        return _render(request)

    current = (request.POST.get('current_password') or '').strip()
    new = (request.POST.get('new_password') or '').strip()
    confirm = (request.POST.get('confirm_password') or '').strip()

    errors = []
    if not current:
        errors.append('请输入当前密码')
    elif not accounts.verify_password(account, current):
        # 历史 MD5 账号在兼容模式关闭时无法自助验证，
        # 必须由管理员发放一次性口令（届时密码已是官方哈希）。
        errors.append('当前密码不正确；若为历史账号请联系管理员重置')
    if new != confirm:
        errors.append('两次输入的新密码不一致')
    if current and new and new == current:
        errors.append('新密码不能与当前密码相同')
    if errors:
        return _render(request, errors=errors)

    try:
        lifecycle.change_password(
            account, account_type, new,
            request=request,
            enforce_policy=lifecycle.lifecycle_enabled(),
            current_session=request.session,
        )
    except lifecycle.PasswordLifecycleError as exc:
        return _render(request, errors=[str(exc)])

    return redirect(accounts.ROLE_HOME_URLS.get(account_type, '/'))


@role_required(accounts.ROLE_ADMIN)
@require_POST
def admin_issue_temp_password(request):
    """管理员发放一次性临时口令。

    参数：``account_type``（admin/student/teacher）与 ``account_id``。
    为防止越权枚举，先校验目标确实存在，再做角色校验。
    """
    account_type = (request.POST.get('account_type') or '').strip()
    account_id = (request.POST.get('account_id') or '').strip()

    model = ACCOUNT_MODELS.get(account_type)
    if model is None:
        return JsonResponse({'status': False, 'error': '未知账号类型'}, status=400)

    target = model.objects.filter(pk=account_id).first()
    if target is None:
        return JsonResponse({'status': False, 'error': '账号不存在'}, status=404)

    try:
        raw, state = lifecycle.issue_temporary_password(
            target, account_type, actor=None, request=request)
    except lifecycle.PasswordLifecycleError as exc:
        return JsonResponse({'status': False, 'error': str(exc)}, status=400)

    payload = {
        'status': True,
        # 明文只在此响应中出现一次，前端展示后即丢弃
        'password': raw,
        'account_type': account_type,
        'account_id': str(target.pk),
        'lifecycle_enabled': lifecycle.lifecycle_enabled(),
        'must_change_password': True,
        'expires_at': (state.temp_password_expires_at.isoformat()
                       if state is not None and state.temp_password_expires_at else None),
    }
    response = JsonResponse(payload)
    # 含一次性口令，禁止任何缓存
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    return response
