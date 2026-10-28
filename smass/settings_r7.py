"""R7 隔离配置：库 ``smass_r7_analytics``（全合成数据）。"""
import os

from .settings_r6 import *  # noqa: F401,F403

R7_DB_NAME = os.environ.get('R7_DB', 'smass_r7_analytics')

if not R7_DB_NAME.startswith('smass_r7_'):
    raise RuntimeError('R7 库名必须命中 smass_r7_ 前缀，当前 {!r}'.format(R7_DB_NAME))

DATABASES['default']['NAME'] = R7_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r7_analytics'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_analytics.apps.SmassAnalyticsConfig']

ROOT_URLCONF = 'smass.urls_r7'