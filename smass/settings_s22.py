"""S22 隔离配置：库 ``smass_s22_drill``（备份恢复演练专用，禁止指向正式库）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S22_DB_NAME = os.environ.get('S22_DB', 'smass_s22_drill')

if not S22_DB_NAME.startswith('smass_s22_'):
    raise RuntimeError('S22 库名必须命中 smass_s22_ 前缀，当前 {!r}'.format(S22_DB_NAME))

DATABASES['default']['NAME'] = S22_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s22_drill'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
]
