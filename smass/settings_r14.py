"""R14 隔离配置：库 ``smass_r14_activities``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R14_DB_NAME = os.environ.get('R14_DB', 'smass_r14_activities')

if not R14_DB_NAME.startswith('smass_r14_'):
    raise RuntimeError('R14 库名必须命中 smass_r14_ 前缀，当前 {!r}'.format(R14_DB_NAME))

DATABASES['default']['NAME'] = R14_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r14_activities'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_activities.apps.SmassActivitiesConfig',
]

ROOT_URLCONF = 'smass.urls_r14'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
