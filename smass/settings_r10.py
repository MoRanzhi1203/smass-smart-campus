"""R10 隔离配置：库 ``smass_r10_release``（发行候选验收）。"""
import os

from .settings_r9 import *  # noqa: F401,F403

R10_DB_NAME = os.environ.get('R10_DB', 'smass_r10_release')

if not R10_DB_NAME.startswith('smass_r10_'):
    raise RuntimeError('R10 库名必须命中 smass_r10_ 前缀，当前 {!r}'.format(R10_DB_NAME))

DATABASES['default']['NAME'] = R10_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r10_release'

ROOT_URLCONF = 'smass.urls_r10'