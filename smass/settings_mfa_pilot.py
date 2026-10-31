"""A03 MFA 试点配置：产品 schema + ``smass_mfa``，独立库 ``smass_mfa_pilot``。

用途：验证“在产品的账号/组织数据模型上迁移并初始化 MFA 设备与恢复码表”，
不改产品主线（``ROOT_URLCONF`` 仍为 ``smass.urls_product``，MFA 路由不挂载，
中间件不启用）。产物：试点库 + 冒烟证据，供 06_Security_Integration.md 引用。
"""
import os

from .settings_product import *  # noqa: F401,F403

PILOT_DB_NAME = os.environ.get('MFA_PILOT_DB', 'smass_mfa_pilot')

if not PILOT_DB_NAME.startswith('smass_mfa_pilot'):
    raise RuntimeError(
        'MFA 试点库名必须命中 smass_mfa_pilot 前缀，当前 {!r}'.format(
            PILOT_DB_NAME))

DATABASES['default']['NAME'] = PILOT_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_mfa_pilot'

INSTALLED_APPS = list(INSTALLED_APPS)
for app in ('smass_organization.apps.SmassOrganizationConfig',
            'smass_mfa.apps.SmassMfaConfig'):
    if app not in INSTALLED_APPS:
        INSTALLED_APPS.append(app)

MFA_ENABLED = True
MFA_REQUIRED_ROLES = ['system_admin']
