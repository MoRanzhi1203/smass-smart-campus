"""
Django settings for smass project.

配置来源约定：
- 所有可变、可能敏感的值都通过环境变量读取（模板见项目根 ``.env.example``）；
- 代码仓库内不保存真实数据库密码与 Secret Key；
- 本地开发把真实值写在 ``.env``（已被 ``.gitignore`` 排除）；
- 生产环境必须显式设置 ``DJANGO_DEBUG=False`` 并注入 ``DJANGO_SECRET_KEY``。

Django 基线：项目由 3.2.5 模板生成，实际运行于 Django 5.2.x。
"""
import logging.handlers
import os
from pathlib import Path

from .env_loader import load_env

# ---------------------------------------------------------------------------
# 基础路径与本地环境变量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# 载入项目根目录 .env（不存在时静默跳过）
load_env(BASE_DIR / '.env')


def env(name, default=None):
    """读取字符串环境变量；空字符串视为未设置。"""
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value


def env_bool(name, default=False):
    """读取布尔环境变量，接受 1/true/yes/on。"""
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name, default=0):
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def env_list(name, default=()):
    """读取逗号分隔的列表环境变量。"""
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return list(default)
    return [item.strip() for item in value.split(',') if item.strip()]


# ---------------------------------------------------------------------------
# 安全基线
# ---------------------------------------------------------------------------
DEBUG = env_bool('DJANGO_DEBUG', True)

SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # 仅开发回退值；生产（DEBUG=False）必须显式提供，否则直接启动失败
        SECRET_KEY = 'django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE'
    else:
        raise RuntimeError(
            '生产模式（DJANGO_DEBUG=False）必须通过环境变量 DJANGO_SECRET_KEY 提供密钥。'
        )

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', ['127.0.0.1', 'localhost'])
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', [])


# ---------------------------------------------------------------------------
# 应用与中间件
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app01.apps.App01Config',
]

# 中间件
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'app01.middleware.auth.AuthMiddleware',
    # 含一次性口令等敏感内容的响应禁止缓存（R1.5-B.7）
    'app01.middleware.privacy.SensitiveResponseMiddleware',
    # S02：会话世代校验 + 强制改密（仅在 PASSWORD_LIFECYCLE['ENABLED'] 时生效）
    'app01.middleware.password_lifecycle.PasswordLifecycleMiddleware',
    # S17：空闲超时与设备活动刷新（仅在 SESSION_SECURITY['ENABLED'] 时生效）
    'app01.middleware.session_security.SessionSecurityMiddleware',
]

ROOT_URLCONF = 'smass.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'smass.wsgi.application'


# ---------------------------------------------------------------------------
# 数据库（MySQL）
# ---------------------------------------------------------------------------
# 注意：历史配置中键名误写为 'POST'，此处已修正为 'PORT'。
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME', 'smass'),
        'USER': env('DB_USER', 'root'),
        'PASSWORD': env('DB_PASSWORD', ''),
        'HOST': env('DB_HOST', 'localhost'),
        'PORT': env('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'TEST': {
            'NAME': env('DB_TEST_NAME', 'test_smass'),
            'CHARSET': 'utf8mb4',
        },
    }
}


# ---------------------------------------------------------------------------
# 密码校验
# ---------------------------------------------------------------------------
# 注意：本项目的业务规则允许 6-10 位字母数字（见 students 改密视图），
# 因此把 Django 的最小长度也设为 6 以保持兼容；其余校验器仍启用，
# 由 services/accounts.password_errors() 在真实写入路径上调用。
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 6},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# ---------------------------------------------------------------------------
# 密码生命周期策略（S02）
# ---------------------------------------------------------------------------
# 全部默认关闭：学校具体密码政策未确认前，不得擅自对真实用户强制改密。
# 需要启用时通过环境变量打开，或直接覆盖本字典。
# 状态数据存放在 app01.AccountSecurityState（独立表，不改既有账号表）。
PASSWORD_LIFECYCLE = {
    # 总开关；关闭时中间件与强制改密拦截完全不起作用
    'ENABLED': env_bool('SMASS_PASSWORD_LIFECYCLE', False),
    # 仍持有 32 位历史 MD5 的账号，在启用后强制改密
    'FORCE_RESET_LEGACY': env_bool('SMASS_FORCE_RESET_LEGACY', False),
    # 被停用的账号强制改密（停用本身已经阻止登录）
    'FORCE_RESET_INACTIVE': env_bool('SMASS_FORCE_RESET_INACTIVE', False),
    # 密码最大使用天数；0 表示不按时间强制
    'MAX_AGE_DAYS': env_int('SMASS_PASSWORD_MAX_AGE_DAYS', 0),
    # 管理员发放的一次性口令有效分钟数
    'TEMP_PASSWORD_TTL_MINUTES': env_int('SMASS_TEMP_PASSWORD_TTL_MINUTES', 1440),
    # 登录时自动识别并登记遗留哈希（不改密码，只登记状态）
    'DETECT_LEGACY_ON_LOGIN': env_bool('SMASS_DETECT_LEGACY_ON_LOGIN', True),
}


# ---------------------------------------------------------------------------
# 国际化（已切换为中文）
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_L10N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# 静态文件与媒体文件
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static')
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
X_FRAME_OPTIONS = 'DENY'


# ---------------------------------------------------------------------------
# 会话与 CSRF
# ---------------------------------------------------------------------------
# 24 小时（与历史注释"七天后"不一致的问题一并修正：注释与实现保持一致）
SESSION_COOKIE_AGE = env_int('DJANGO_SESSION_COOKIE_AGE', 60 * 60 * 24)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
# 允许前端通过 X-CSRFToken 头提交令牌
CSRF_HEADER_NAME = 'HTTP_X_CSRFTOKEN'
CSRF_COOKIE_HTTPONLY = False

# S17：空闲超时与设备会话（默认关闭，避免影响既有部署）
SESSION_SECURITY = {
    'ENABLED': env_bool('DJANGO_SESSION_IDLE_ENABLED', False),
    'IDLE_TIMEOUT_MINUTES': env_int('DJANGO_SESSION_IDLE_MINUTES', 30),
}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', False)
    SECURE_HSTS_SECONDS = env_int('DJANGO_SECURE_HSTS_SECONDS', 0)
    if env_bool('DJANGO_BEHIND_PROXY', False):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# ---------------------------------------------------------------------------
# 日志（不记录密码、哈希、身份证完整号码等敏感值）
# ---------------------------------------------------------------------------
LOG_DIR = Path(env('DJANGO_LOG_DIR', str(BASE_DIR / 'logs')))
# 目录不存在时 RotatingFileHandler 会初始化失败，这里提前创建
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'smass.log'),
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': env('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        # 业务审计日志通道
        'smass.audit': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        # ORM SQL 噪音默认降到 WARNING
        'django.db.backends': {
            'level': 'WARNING',
        },
    },
}
