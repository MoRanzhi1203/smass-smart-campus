"""R18 隔离配置：库 ``smass_r18_finance``（全合成数据，无真实支付）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R18_DB_NAME = os.environ.get('R18_DB', 'smass_r18_finance')

if not R18_DB_NAME.startswith('smass_r18_'):
    raise RuntimeError('R18 库名必须命中 smass_r18_ 前缀，当前 {!r}'.format(R18_DB_NAME))

DATABASES['default']['NAME'] = R18_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r18_finance'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_finance.apps.SmassFinanceConfig',
]

ROOT_URLCONF = 'smass.urls_r18'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'

#: 明确声明本环境不做真实支付（防止误接网关）
SMASS_FINANCE_SYNTHETIC_ONLY = True
