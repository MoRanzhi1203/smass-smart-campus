"""S11 隔离配置：库 ``smass_s11_policy``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S11_DB_NAME = os.environ.get('S11_DB', 'smass_s11_policy')

if not S11_DB_NAME.startswith('smass_s11_'):
    raise RuntimeError('S11 库名必须命中 smass_s11_ 前缀，当前 {!r}'.format(S11_DB_NAME))

DATABASES['default']['NAME'] = S11_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s11_policy'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_policy.apps.SmassPolicyConfig',
]

ROOT_URLCONF = 'smass.urls_s11'

LOGIN_URL = '/r21/login/'
