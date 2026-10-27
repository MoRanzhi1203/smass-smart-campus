"""R2.1 原型配置（隔离库 ``smass_r21_proto``）。

与正式 ``smass.settings`` 的差异（刻意保持最小集）：

1. 数据库固定为 ``smass_r21_proto``；
2. 追加 ``r21_account`` app，并把 ``AUTHENTICATION_BACKENDS`` 指向 ``AccountBackend``；
3. **移除** ``app01.middleware.auth.AuthMiddleware`` —— 它基于
   ``session['info']``（旧的三表身份），与统一认证会互相矛盾；R2.1 环境只认
   ``request.user``；
4. ``ROOT_URLCONF`` 指向 ``smass.urls_r21``（只含 R2.1 的认证与改密路由），
   避免 app01 业务视图在"未切换"状态下被误访问；
5. 追加 R2.1 自己的中间件（强制改密 / 持久化限速）。

正式 ``smass`` 库的认证路径、``AUTH_USER_MODEL`` 均**未改变**。
"""
from .settings import *  # noqa: F401,F403

R21_DB_NAME = 'smass_r21_proto'

if DATABASES['default']['NAME'] != 'smass':
    raise RuntimeError(
        'R2.1 原型只允许从开发库 smass 派生，当前 {!r}'.format(
            DATABASES['default']['NAME']
        )
    )

DATABASES['default']['NAME'] = R21_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r21_proto'

INSTALLED_APPS = list(INSTALLED_APPS) + ['r21_account.apps.R21AccountConfig']

AUTHENTICATION_BACKENDS = ['r21_account.backends.AccountBackend']

ROOT_URLCONF = 'smass.urls_r21'

_TEMPLATE_DIRS = list(TEMPLATES[0]['DIRS'])

MIDDLEWARE = [m for m in MIDDLEWARE if m != 'app01.middleware.auth.AuthMiddleware']
MIDDLEWARE = list(MIDDLEWARE) + [
    'r21_account.middleware.ForcePasswordChangeMiddleware',
]

# 登录限速参数（可被环境变量覆盖，便于测试与运维调参）
R21_LOGIN_RATE_LIMIT = {
    'window_seconds': 900,        # 15 分钟窗口
    'max_per_login_ip': 5,        # 同一账号+IP 失败 5 次即锁定
    'max_per_login': 20,          # 同一账号跨 IP 失败 20 次也锁定（防分布式撞库）
    'lock_seconds': 900,          # 锁定时长
}

# 强制改密的白名单（这些路径在 must_change_password=True 时仍可访问）
R21_PASSWORD_CHANGE_EXEMPT = (
    '/r21/change-password/',
    '/r21/logout/',
    '/r21/login/',
    '/static/',
    '/media/',
)
