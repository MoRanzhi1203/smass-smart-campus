"""R2.2 G5 演练配置：库固定为隔离 stage（``smass_r22_g5_stage``）。

安全约束：
- 只允许 ``smass_r22_g5_`` 前缀；
- 源库 ``smass`` 只读，本配置从不指向它；
- 不修改任何正式配置。
"""
import os

from .settings import *  # noqa: F401,F403

G5_DB_NAME = os.environ.get('R22_G5_DB', 'smass_r22_g5_stage')

if not G5_DB_NAME.startswith('smass_r22_g5_'):
    raise RuntimeError(
        'G5 演练库名必须命中 smass_r22_g5_ 前缀，当前 {!r}'.format(G5_DB_NAME)
    )
if DATABASES['default']['NAME'] != 'smass':
    raise RuntimeError(
        'G5 演练配置只允许从开发库 smass 派生，当前 {!r}'.format(
            DATABASES['default']['NAME']
        )
    )

DATABASES['default']['NAME'] = G5_DB_NAME

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'r21_account.apps.R21AccountConfig',
    'r22_account.apps.R22AccountConfig',
]

ROOT_URLCONF = 'smass.urls_r22'

MIDDLEWARE = [m for m in MIDDLEWARE if m != 'app01.middleware.auth.AuthMiddleware']

R22_FLAGS = {
    'identity_mode': 'dual',
    'route_policy_enabled': True,
    'audit_enabled': True,
    'dry_run': False,
}
