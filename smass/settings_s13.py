"""S13 隔离配置：库 ``smass_s13_privacy``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S13_DB_NAME = os.environ.get('S13_DB', 'smass_s13_privacy')

if not S13_DB_NAME.startswith('smass_s13_'):
    raise RuntimeError('S13 库名必须命中 smass_s13_ 前缀，当前 {!r}'.format(S13_DB_NAME))

DATABASES['default']['NAME'] = S13_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s13_privacy'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_privacy.apps.SmassPrivacyConfig',
]

ROOT_URLCONF = 'smass.urls_s13'

LOGIN_URL = '/r21/login/'
