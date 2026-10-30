"""S09 中间件：特权角色强制 MFA。"""
from __future__ import annotations

from urllib.parse import quote

from django.shortcuts import redirect

from . import services

#: 这些前缀不拦截（绑定/验证/退出/静态资源）
ALLOW_PREFIXES = (
    '/s09/',
    '/r21/login/',
    '/r21/logout/',
    '/static/',
    '/media/',
)


class MfaRequiredMiddleware:
    """特权角色未启用 MFA → 强制绑定；已启用但会话未验证 → 强制二次验证。

    关闭 ``settings.MFA_ENABLED`` 时中间件完全透明，不改变既有登录行为。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (user is not None
                and getattr(user, 'is_authenticated', False)
                and services.mfa_enabled()
                and services.is_privileged(user)):
            path = request.path
            if not path.startswith(ALLOW_PREFIXES):
                target = request.get_full_path()
                if services.needs_setup(user):
                    return redirect('/s09/setup/?next={}'.format(quote(target)))
                if not services.session_verified(request.session):
                    return redirect('/s09/verify/?next={}'.format(quote(target)))
        return self.get_response(request)
