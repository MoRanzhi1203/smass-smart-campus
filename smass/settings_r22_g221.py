"""R2.2.1 规模测试配置：库固定为 ``smass_r22_g221_scale``（全合成）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

SCALE_DB_NAME = os.environ.get('R22_SCALE_DB', 'smass_r22_g221_scale')

if not SCALE_DB_NAME.startswith('smass_r22_g221_'):
    raise RuntimeError(
        '规模测试库名必须命中 smass_r22_g221_ 前缀，当前 {!r}'.format(SCALE_DB_NAME)
    )

DATABASES['default']['NAME'] = SCALE_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r22_g221_scale'
