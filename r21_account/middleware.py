"""R2.1 中间件：强制改密。

行为：``request.user`` 已登录但 ``must_change_password=True`` 时，除白名单路径外
一律重定向到改密页（GET 与 AJAX 都按此处理；AJAX 返回 403 JSON 便于前端处理）。

覆盖三端：因为 R2.1 使用**统一 Account**，管理员/教师/学生共用同一套逻辑，
不存在"某端漏做"的可能。
"""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt = tuple(
            getattr(
                settings,
                'R21_PASSWORD_CHANGE_EXEMPT',
                ('/r21/change-password/', '/r21/logout/', '/r21/login/'),
            )
        )

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if user is not None and user.is_authenticated:
            if getattr(user, 'must_change_password', False):
                path = request.path
                if not path.startswith(self.exempt):
                    if self._is_ajax(request):
                        return JsonResponse(
                            {
                                'status': False,
                                'code': 'must_change_password',
                                'tips': '首次登录需先修改密码',
                            },
                            status=403,
                        )
                    return redirect('/r21/change-password/')

        return self.get_response(request)

    @staticmethod
    def _is_ajax(request):
        return (
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', '')
        )
