"""集成开发配置：**单一隔离库** ``smass_integrated_dev``，统一 R10 管理后台与 R11–R20 业务。

用途
----
让评审者在一个进程、一个数据库、一个登录入口里看到：
- R10 统一管理后台（`/r10/`）与 R4–R9 业务页面（`/r4/` … `/r9/`）；
- R11 排课（`/r11/`）、R12–R15 学工/团委业务（`/r12/` … `/r15/`）、
  R16 场地（`/r16/`）、R17–R19 业务（`/r17/` … `/r19/`）、R20 门户（`/r20/`）；
- 统一入口 `/hub/`（登录后按角色展示可进入的模块）。

约束
----
- 库名硬校验 ``smass_integrated_dev``，**绝不指向正式库 ``smass``**；
- 继承 ``settings_r10``（含 r21 统一账号、R4–R9 全部 app 与中间件）；
- 不改 ``smass.settings`` / 正式入口 / 认证切换状态（正式仍走旧系统）；
- 全部为合成数据，可随时删库重建（见 ``scripts/integrated_dev_bootstrap.py``）。
"""
import os

from .settings_r10 import *  # noqa: F401,F403

INTEGRATED_DB_NAME = os.environ.get('INTEGRATED_DB', 'smass_integrated_dev')

if not INTEGRATED_DB_NAME.startswith('smass_integrated_dev'):
    raise RuntimeError(
        '集成开发库必须命中 smass_integrated_dev 前缀，当前 {!r}'.format(
            INTEGRATED_DB_NAME))
if INTEGRATED_DB_NAME == 'smass':
    raise RuntimeError('集成开发配置禁止指向正式库 smass')

DATABASES['default']['NAME'] = INTEGRATED_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_integrated_dev'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_scheduling.apps.SmassSchedulingConfig',
    'smass_enrollment.apps.SmassEnrollmentConfig',
    'smass_attendance.apps.SmassAttendanceConfig',
    'smass_activities.apps.SmassActivitiesConfig',
    'smass_clubs.apps.SmassClubsConfig',
    'smass_facilities.apps.SmassFacilitiesConfig',
    'smass_forum.apps.SmassForumConfig',
    'smass_finance.apps.SmassFinanceConfig',
    'smass_party.apps.SmassPartyConfig',
    'smass_portal.apps.SmassPortalConfig',
]

ROOT_URLCONF = 'smass.urls_integrated_dev'

# 统一登录入口（R21 账号体系）
LOGIN_URL = '/r21/login/'
LOGIN_REDIRECT_URL = '/hub/'

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']
