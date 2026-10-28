"""R9 隔离配置：库 ``smass_r9_ops``（全合成数据）。"""
import os

from .settings_r8 import *  # noqa: F401,F403

R9_DB_NAME = os.environ.get('R9_DB', 'smass_r9_ops')

if not R9_DB_NAME.startswith('smass_r9_'):
    raise RuntimeError('R9 库名必须命中 smass_r9_ 前缀，当前 {!r}'.format(R9_DB_NAME))

DATABASES['default']['NAME'] = R9_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r9_ops'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_operations.apps.SmassOperationsConfig']

ROOT_URLCONF = 'smass.urls_r9'

MIDDLEWARE = list(MIDDLEWARE) + ['smass_operations.middleware.RequestMetricsMiddleware']