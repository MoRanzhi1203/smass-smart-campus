"""R5 隔离配置：库 ``smass_r5_academic``（全合成数据）。"""
import os

from .settings_r4 import *  # noqa: F401,F403

R5_DB_NAME = os.environ.get('R5_DB', 'smass_r5_academic')

if not R5_DB_NAME.startswith('smass_r5_'):
    raise RuntimeError('R5 库名必须命中 smass_r5_ 前缀，当前 {!r}'.format(R5_DB_NAME))

DATABASES['default']['NAME'] = R5_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r5_academic'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_academic.apps.SmassAcademicConfig']

ROOT_URLCONF = 'smass.urls_r5'

# S25 数据交换中心：R5 的登录页与 R4 不同
LOGIN_URL = '/r5/login/'
