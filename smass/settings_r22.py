"""R2.2 隔离配置（库 ``smass_r22_proto``）。

与正式 ``smass.settings`` 的关键差异：
1. 库指向 ``smass_r22_proto``（正式库只读）；
2. 追加 ``r21_account``（统一账号）与 ``r22_account``（身份兼容层）；
3. 认证后端仍为 ``AccountBackend``，**``AUTH_USER_MODEL`` 保持 ``auth.User``**（路径 A）；
4. 移除 ``app01`` 的旧 ``AuthMiddleware``，改由 ``r22_account`` 的
   ``IdentityMiddleware`` + ``RoutePolicyMiddleware`` 统一处理；
5. 全部新行为由 ``R22_FLAGS`` 控制，**默认只在隔离配置下开启**。

正式 ``smass.settings`` 不加载本文件，因此正式系统行为不变。
"""
from .settings import *  # noqa: F401,F403

R22_DB_NAME = 'smass_r22_proto'

if DATABASES['default']['NAME'] != 'smass':
    raise RuntimeError(
        'R2.2 隔离配置只允许从开发库 smass 派生，当前 {!r}'.format(
            DATABASES['default']['NAME']
        )
    )

DATABASES['default']['NAME'] = R22_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r22_proto'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'r21_account.apps.R21AccountConfig',
    'r22_account.apps.R22AccountConfig',
]

# 路径 A：AUTH_USER_MODEL 不变，仅替换认证后端
AUTHENTICATION_BACKENDS = ['r21_account.backends.AccountBackend']

ROOT_URLCONF = 'smass.urls_r22'

MIDDLEWARE = [m for m in MIDDLEWARE if m != 'app01.middleware.auth.AuthMiddleware']
MIDDLEWARE = list(MIDDLEWARE) + [
    'r21_account.middleware.ForcePasswordChangeMiddleware',
    # 顺序：Identity 必须晚于 AuthenticationMiddleware（依赖 request.user）；
    #       RoutePolicy 必须晚于 Identity（依赖解析结果）。
    'r22_account.middleware.IdentityMiddleware',
    'r22_account.middleware.RoutePolicyMiddleware',
]

# ---- R2.2 特性开关（隔离配置专属；正式配置无此键 = 全部关闭）----
R22_FLAGS = {
    'identity_mode': 'dual',      # off | account | dual
    'route_policy_enabled': True,
    'audit_enabled': True,
    'dry_run': False,
}

R21_PASSWORD_CHANGE_EXEMPT = (
    '/r21/change-password/',
    '/r21/logout/',
    '/r21/login/',
    '/static/',
    '/media/',
)

R21_LOGIN_RATE_LIMIT = {
    'window_seconds': 900,
    'max_per_login_ip': 5,
    'max_per_login': 20,
    'lock_seconds': 900,
}
