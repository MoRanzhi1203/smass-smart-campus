"""R19 隔离配置：库 ``smass_r19_party``（全合成数据，不接真实党建材料）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R19_DB_NAME = os.environ.get('R19_DB', 'smass_r19_party')

if not R19_DB_NAME.startswith('smass_r19_'):
    raise RuntimeError('R19 库名必须命中 smass_r19_ 前缀，当前 {!r}'.format(R19_DB_NAME))

DATABASES['default']['NAME'] = R19_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r19_party'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_party.apps.SmassPartyConfig',
]

ROOT_URLCONF = 'smass.urls_r19'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'

#: 明确声明不接入真实党建敏感资料
SMASS_PARTY_SYNTHETIC_ONLY = True
