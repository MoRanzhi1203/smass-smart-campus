"""S16 隔离配置：库 ``smass_s16_audit``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S16_DB_NAME = os.environ.get('S16_DB', 'smass_s16_audit')

if not S16_DB_NAME.startswith('smass_s16_'):
    raise RuntimeError('S16 库名必须命中 smass_s16_ 前缀，当前 {!r}'.format(S16_DB_NAME))

DATABASES['default']['NAME'] = S16_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s16_audit'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_audit.apps.SmassAuditConfig',
]

ROOT_URLCONF = 'smass.urls_s16'

LOGIN_URL = '/r21/login/'
