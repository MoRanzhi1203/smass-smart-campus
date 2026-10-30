"""R15 隔离配置：库 ``smass_r15_clubs``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R15_DB_NAME = os.environ.get('R15_DB', 'smass_r15_clubs')

if not R15_DB_NAME.startswith('smass_r15_'):
    raise RuntimeError('R15 库名必须命中 smass_r15_ 前缀，当前 {!r}'.format(R15_DB_NAME))

DATABASES['default']['NAME'] = R15_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r15_clubs'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_clubs.apps.SmassClubsConfig',
]

ROOT_URLCONF = 'smass.urls_r15'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
