"""S02 中间件：会话世代校验 + 强制改密拦截。

与既有 ``app01.middleware.auth.AuthMiddleware`` 的分工：
- ``AuthMiddleware`` 只做**URL 前缀的角色粗粒度准入**；
- 本中间件处理**账号安全状态**：会话是否已被新世代作废、是否必须先改密。

默认**不生效**：只有当 ``settings.PASSWORD_LIFECYCLE['ENABLED']`` 为真时才拦截。
这样既有 930+ 用例与正式库（未迁移状态表）的行为完全不变。
"""
from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from app01.services import password_lifecycle as lifecycle

#: 登录态下仍必须放行的路径前缀（否则用户无法登录/改密/登出）
EXEMPT_PREFIXES = (
    '/login/',
    '/logout/',
    '/account/password/forced/',
    '/admin/admin/resetPass/',
    '/static/',
    '/media/',
    '/favicon.ico',
)

#: 强制改密页地址
FORCED_CHANGE_URL = '/account/password/forced/'


def wants_json(request):
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


def _is_exempt(path):
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


class PasswordLifecycleMiddleware(MiddlewareMixin):
    """按账号安全状态拦截请求。"""

    def process_request(self, request):
        if not lifecycle.lifecycle_enabled():
            return None

        info = request.session.get('info') or {}
        account_type = info.get('type')
        account_id = info.get('id')
        if not account_type or not account_id:
            return None  # 未登录：交给 AuthMiddleware 处理

        path = request.path

        # ---- 1. 会话世代：重置/停用/改密后旧会话必须失效 ----
        if not lifecycle.session_is_current(account_type, account_id, request.session):
            request.session.flush()
            return self._deny_session(request, path)

        # ---- 2. 强制改密 ----
        state = lifecycle.get_state(account_type, account_id)
        if state is not None and state.must_change_password and not _is_exempt(path):
            return self._require_change(request)

        return None

    @staticmethod
    def _deny_session(request, path):
        if wants_json(request):
            return JsonResponse(
                {'status': False, 'code': 'session_expired',
                 'tips': '登录状态已失效（密码或账号状态已变更），请重新登录'},
                status=401,
            )
        login = '/login/account/{}/'.format(
            (request.session.get('info') or {}).get('type') or 'student')
        target = request.get_full_path()
        if target.startswith('/'):
            return redirect('{}?next={}'.format(login, quote(target)))
        return redirect(login)

    @staticmethod
    def _require_change(request):
        if wants_json(request):
            return JsonResponse(
                {'status': False, 'code': 'must_change_password',
                 'tips': '请先修改密码后再继续操作'},
                status=403,
            )
        return redirect(FORCED_CHANGE_URL)
