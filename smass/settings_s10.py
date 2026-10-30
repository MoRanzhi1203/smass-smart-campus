"""S10 隔离配置：库 ``smass_s10_stepup``（全合成数据）。

同时装载 ``smass_mfa``：再认证支持 TOTP。
"""
import os

from .settings_r22 import *  # noqa: F401,F403

S10_DB_NAME = os.environ.get('S10_DB', 'smass_s10_stepup')

if not S10_DB_NAME.startswith('smass_s10_'):
    raise RuntimeError('S10 库名必须命中 smass_s10_ 前缀，当前 {!r}'.format(S10_DB_NAME))

DATABASES['default']['NAME'] = S10_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s10_stepup'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_mfa.apps.SmassMfaConfig',
    'smass_stepup.apps.SmassStepupConfig',
]

ROOT_URLCONF = 'smass.urls_s10'

MFA_ENABLED = True
MFA_REQUIRED_ROLES = ['system_admin', 'college_admin']

LOGIN_URL = '/r21/login/'
