"""R17 隔离配置：库 ``smass_r17_forum``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R17_DB_NAME = os.environ.get('R17_DB', 'smass_r17_forum')

if not R17_DB_NAME.startswith('smass_r17_'):
    raise RuntimeError('R17 库名必须命中 smass_r17_ 前缀，当前 {!r}'.format(R17_DB_NAME))

DATABASES['default']['NAME'] = R17_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r17_forum'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_forum.apps.SmassForumConfig',
]

ROOT_URLCONF = 'smass.urls_r17'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
