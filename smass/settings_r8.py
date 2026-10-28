"""R8 隔离配置：库 ``smass_r8_api``（全合成数据）。"""
import os

from .settings_r7 import *  # noqa: F401,F403

R8_DB_NAME = os.environ.get('R8_DB', 'smass_r8_api')

if not R8_DB_NAME.startswith('smass_r8_'):
    raise RuntimeError('R8 库名必须命中 smass_r8_ 前缀，当前 {!r}'.format(R8_DB_NAME))

DATABASES['default']['NAME'] = R8_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r8_api'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_api.apps.SmassApiConfig']

ROOT_URLCONF = 'smass.urls_r8'