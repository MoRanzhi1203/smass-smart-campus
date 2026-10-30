"""R20 隔离配置：库 ``smass_r20_portal``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R20_DB_NAME = os.environ.get('R20_DB', 'smass_r20_portal')

if not R20_DB_NAME.startswith('smass_r20_'):
    raise RuntimeError('R20 库名必须命中 smass_r20_ 前缀，当前 {!r}'.format(R20_DB_NAME))

DATABASES['default']['NAME'] = R20_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r20_portal'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_portal.apps.SmassPortalConfig',
]

ROOT_URLCONF = 'smass.urls_r20'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
