"""R13 隔离配置：库 ``smass_r13_attendance``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R13_DB_NAME = os.environ.get('R13_DB', 'smass_r13_attendance')

if not R13_DB_NAME.startswith('smass_r13_'):
    raise RuntimeError('R13 库名必须命中 smass_r13_ 前缀，当前 {!r}'.format(R13_DB_NAME))

DATABASES['default']['NAME'] = R13_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r13_attendance'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_attendance.apps.SmassAttendanceConfig',
]

ROOT_URLCONF = 'smass.urls_r13'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
