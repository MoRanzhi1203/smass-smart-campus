"""视图级角色权限装饰器。

中间件（``app01.middleware.auth``）只按 URL 前缀做**第一道粗筛**；
真正的准入必须落在视图上，否则新增一个未加前缀的路由就会绕过全部检查。
"""
from functools import wraps
from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect

from app01.services.accounts import ROLE_LOGIN_URLS


def wants_json(request):
    """判断请求是否期望 JSON 响应（AJAX 或显式 Accept）。"""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


def role_required(*roles):
    """要求当前会话角色属于 *roles*。

    - 未登录：AJAX 返回 403 JSON，页面请求跳转登录页并携带 ``next``；
    - 角色不符：同样拒绝（不做"静默降级到其他角色首页"，避免误导）。
    """
    allowed = tuple(roles)
    primary_role = allowed[0] if allowed else 'admin'

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            info = request.session.get('info')
            role = (info or {}).get('type')

            if role in allowed:
                return view_func(request, *args, **kwargs)

            if wants_json(request):
                return JsonResponse(
                    {'status': False, 'tips': '登录状态失效或无权限，请重新登录'},
                    status=403,
                )

            if not role:
                login_url = ROLE_LOGIN_URLS.get(primary_role, '/login/')
                target = request.get_full_path()
                if target.startswith('/'):
                    return redirect('{}?next={}'.format(login_url, quote(target)))
                return redirect(login_url)

            # 已登录但角色不符：直接拒绝，避免跨角色重定向造成死循环
            return JsonResponse(
                {'status': False, 'tips': '当前角色无权访问该页面'},
                status=403,
            )

        return _wrapped

    return decorator


def admin_required(view_func):
    """管理员专用。"""
    return role_required('admin')(view_func)


def student_required(view_func):
    """学生专用。"""
    return role_required('student')(view_func)


def teacher_required(view_func):
    """教师专用。"""
    return role_required('teacher')(view_func)
