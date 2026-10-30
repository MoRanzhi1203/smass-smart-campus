"""S15 隔离配置：库 ``smass_s15_api``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S15_DB_NAME = os.environ.get('S15_DB', 'smass_s15_api')

if not S15_DB_NAME.startswith('smass_s15_'):
    raise RuntimeError('S15 库名必须命中 smass_s15_ 前缀，当前 {!r}'.format(S15_DB_NAME))

DATABASES['default']['NAME'] = S15_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s15_api'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_api_security.apps.SmassApiSecurityConfig',
]

ROOT_URLCONF = 'smass.urls_s15'

LOGIN_URL = '/r21/login/'
