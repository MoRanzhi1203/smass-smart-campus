"""G2/G4 中间件：``request.account`` 契约与路由策略。

设计约束：
1. **不改 ``request.user``**（不做 monkeypatch，不把 ``auth.User`` 当成 Account）；
2. 懒解析 + 请求级缓存：未使用身份时不额外查库；
3. 路由策略与身份解析**分离**：``RoutePolicyMiddleware`` 只根据解析结果拒绝，
   不改变身份本身的判定；
4. 正式 ``settings`` 不加载本中间件。
"""
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.functional import SimpleLazyObject

from r22_account import conf
from r22_account.identity import resolve_identity


#: 需要走 legacy 桥接的旧业务路由前缀
LEGACY_PATH_PREFIXES = ('/admin/', '/student/', '/teacher/')


def wants_json(request):
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


class IdentityMiddleware:
    """在 ``request`` 上暴露 ``account`` / ``legacy_identity`` / ``r22_identity``。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cache = {'identity': None}

        def _get_identity():
            if cache['identity'] is None:
                cache['identity'] = resolve_identity(request)
            return cache['identity']

        # 对外契约：request.r22_identity() 返回 Identity（带缓存）
        # H3: expose cache so the legacy bridge can invalidate it after
        # writing session['info'] (otherwise RoutePolicy sees a stale kind)
        request._r22_identity_cache = cache
        request.r22_identity = _get_identity
        # Account 或 None：保证不会把 auth.User 当成 Account
        request.account = SimpleLazyObject(lambda: _get_identity().account)
        # 旧身份（规范化后的 session['info']）或 None，与 account 分开
        request.legacy_identity = SimpleLazyObject(lambda: _get_identity().legacy)

        # H3: only bridge session['info'] on legacy business routes
        if request.path.startswith(LEGACY_PATH_PREFIXES):
            from r22_account.legacy_compat import ensure_legacy_session
            ensure_legacy_session(request)

        return self.get_response(request)


#: 路由 -> 允许的身份类型
ROUTE_POLICY = (
    ('/admin/', ('legacy', 'dual')),
    ('/student/', ('legacy', 'dual')),
    ('/teacher/', ('legacy', 'dual')),
    ('/legacy-parity/', ('legacy', 'dual')),
    ('/r21/', ('account', 'dual')),
    ('/r22/', ('account', 'dual')),
)

#: 这些路径必须在"未登录"时也能访问（否则登录流程本身会被策略挡住）
POLICY_EXEMPT_PREFIXES = (
    '/r21/login/',
    '/r21/logout/',
    '/r21/change-password/',
    '/identity/',
)


def resolve_route_policy(path):
    for prefix, allowed in ROUTE_POLICY:
        if path.startswith(prefix):
            return prefix, allowed
    return None, None


class RoutePolicyMiddleware:
    """按"路由策略 × 身份类型"做准入。

    - 冲突（conflict）在任何受限路由上一律拒绝；
    - 匿名在受限路由上拒绝并跳登录；
    - legacy 身份不能进 account 路由，反之亦然（不做权限并集）。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not conf.flags()['route_policy_enabled']:
            return self.get_response(request)

        if request.path.startswith(POLICY_EXEMPT_PREFIXES):
            return self.get_response(request)

        prefix, allowed = resolve_route_policy(request.path)
        if prefix is None:
            return self.get_response(request)

        identity = request.r22_identity()

        if identity.kind == 'conflict':
            from r22_account import alerts
            alerts.identity_conflict(identity, path=request.path)
            return self._deny(request, '身份冲突：新旧账号映射不一致，已拒绝并记录')

        if identity.kind == 'anonymous':
            return self._deny(request, '登录状态失效，请重新登录')

        if identity.kind not in allowed:
            return self._deny(request, '当前身份类型无权访问该路由')

        return self.get_response(request)

    @staticmethod
    def _deny(request, message):
        if wants_json(request):
            return JsonResponse({'status': False, 'tips': message}, status=403)
        # R2.2 隔离配置下唯一的登录入口是 /r21/login/；
        # 跳 /login/ 会 404（旧登录页未在 urls_r22 挂载）。
        return redirect('/r21/login/')
