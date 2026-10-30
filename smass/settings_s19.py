"""S19 隔离配置：库 ``smass_s19_a11y``（无模型，仅审计报告）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S19_DB_NAME = os.environ.get('S19_DB', 'smass_s19_a11y')

if not S19_DB_NAME.startswith('smass_s19_'):
    raise RuntimeError('S19 库名必须命中 smass_s19_ 前缀，当前 {!r}'.format(S19_DB_NAME))

DATABASES['default']['NAME'] = S19_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s19_a11y'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_a11y.apps.SmassA11yConfig',
]

ROOT_URLCONF = 'smass.urls_s19'

LOGIN_URL = '/r21/login/'
