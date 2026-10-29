"""R4 隔离配置：库 ``smass_r4_org``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

R4_DB_NAME = os.environ.get('R4_DB', 'smass_r4_org')

if not R4_DB_NAME.startswith('smass_r4_'):
    raise RuntimeError('R4 库名必须命中 smass_r4_ 前缀，当前 {!r}'.format(R4_DB_NAME))

DATABASES['default']['NAME'] = R4_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r4_org'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_organization.apps.SmassOrganizationConfig']

# R4 阶段暂不挂 r22 路由（只测模型/服务/视图）
ROOT_URLCONF = 'smass.urls_r4'

MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith('r22_account.')]

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

# S25 数据交换中心：未登录时的跳转目标
LOGIN_URL = '/r4/login/'
