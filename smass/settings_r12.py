"""R12 隔离配置：库 ``smass_r12_enrollment``（全合成数据）。

R12 需要统一账号（授权）与学籍档案（R4），因此继承 ``settings_r22``。
"""
import os

from .settings_r22 import *  # noqa: F401,F403

R12_DB_NAME = os.environ.get('R12_DB', 'smass_r12_enrollment')

if not R12_DB_NAME.startswith('smass_r12_'):
    raise RuntimeError('R12 库名必须命中 smass_r12_ 前缀，当前 {!r}'.format(R12_DB_NAME))

DATABASES['default']['NAME'] = R12_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r12_enrollment'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    # R12 依赖 R4 的学籍档案与组织单元
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_enrollment.apps.SmassEnrollmentConfig',
]

ROOT_URLCONF = 'smass.urls_r12'

# R12 阶段不启用身份路由策略（只测模型/服务/视图）
R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r21/login/'
