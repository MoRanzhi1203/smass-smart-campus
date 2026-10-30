"""S23 隔离配置：库 ``smass_s23_bench``（容量与限流压测专用）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S23_DB_NAME = os.environ.get('S23_DB', 'smass_s23_bench')

if not S23_DB_NAME.startswith('smass_s23_'):
    raise RuntimeError('S23 库名必须命中 smass_s23_ 前缀，当前 {!r}'.format(S23_DB_NAME))

DATABASES['default']['NAME'] = S23_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s23_bench'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_mfa.apps.SmassMfaConfig',
    'smass_api_security.apps.SmassApiSecurityConfig',
    'smass_a11y.apps.SmassA11yConfig',
]

ROOT_URLCONF = 'smass.urls_s23'

#: 压测通过 django.test.Client 发起，需要放行其默认 Host
ALLOWED_HOSTS = ['*']

LOGIN_URL = '/r21/login/'
