"""S09 隔离配置：库 ``smass_s09_mfa``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S09_DB_NAME = os.environ.get('S09_DB', 'smass_s09_mfa')

if not S09_DB_NAME.startswith('smass_s09_'):
    raise RuntimeError('S09 库名必须命中 smass_s09_ 前缀，当前 {!r}'.format(S09_DB_NAME))

DATABASES['default']['NAME'] = S09_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s09_mfa'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_mfa.apps.SmassMfaConfig',
]

ROOT_URLCONF = 'smass.urls_s09'

#: 特权 MFA 总开关与要求角色（可配置；关闭时不改变既有登录行为）
MFA_ENABLED = True
MFA_REQUIRED_ROLES = ['system_admin', 'college_admin']

MIDDLEWARE = list(MIDDLEWARE) + ['smass_mfa.middleware.MfaRequiredMiddleware']

LOGIN_URL = '/r21/login/'
