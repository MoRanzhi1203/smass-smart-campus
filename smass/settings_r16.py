"""R16 隔离配置：库 ``smass_r16_facilities``（全合成数据）。

R16 需要统一账号（授权）与场地模型，因此继承 ``settings_r22``。
"""
import os

from .settings_r22 import *  # noqa: F401,F403

R16_DB_NAME = os.environ.get('R16_DB', 'smass_r16_facilities')

if not R16_DB_NAME.startswith('smass_r16_'):
    raise RuntimeError('R16 库名必须命中 smass_r16_ 前缀，当前 {!r}'.format(R16_DB_NAME))

DATABASES['default']['NAME'] = R16_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r16_facilities'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_facilities.apps.SmassFacilitiesConfig']

ROOT_URLCONF = 'smass.urls_r22'

# R16 阶段不启用身份路由策略（只测模型/服务/视图）
R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
