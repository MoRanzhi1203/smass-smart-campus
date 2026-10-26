"""角色准入中间件。

职责边界（重要）：
- 本中间件只做**基于 URL 前缀的粗粒度准入**，用于挡住最直接的越权访问；
- 细粒度授权（对象归属、角色、字段可写性）由 ``app01.utils.authz`` 的视图装饰器
  与业务查询共同保证。**不得**仅依赖本中间件做安全边界。

历史问题：``/teacher/*`` 分支曾为 ``pass``，等于匿名可直接进入教师页面。
"""
from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from app01.services.accounts import ROLE_LOGIN_URLS


def wants_json(request):
    """判断请求是否期望 JSON 响应。"""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


class AuthMiddleware(MiddlewareMixin):
    """按 URL 前缀校验会话角色。"""

    #: 前缀 -> 允许的角色（顺序无关，均为绝对前缀匹配）
    ROLE_PREFIXES = (
        ('/admin/', 'admin'),
        ('/student/', 'student'),
        ('/teacher/', 'teacher'),
    )

    def process_request(self, request):
        path = request.path

        for prefix, role in self.ROLE_PREFIXES:
            if not path.startswith(prefix):
                continue

            info = request.session.get('info')
            if info and info.get('type') == role:
                return None

            return self._deny(request, role)

        return None

    @staticmethod
    def _deny(request, role):
        """拒绝访问：AJAX 返回 403 JSON，页面请求跳转对应角色登录页。"""
        if wants_json(request):
            return JsonResponse(
                {'status': False, 'tips': '登录状态失效或无权限，请重新登录'},
                status=403,
            )

        login_url = ROLE_LOGIN_URLS.get(role, '/login/')
        target = request.get_full_path()
        if target.startswith('/'):
            return redirect('{}?next={}'.format(login_url, quote(target)))
        return redirect(login_url)
