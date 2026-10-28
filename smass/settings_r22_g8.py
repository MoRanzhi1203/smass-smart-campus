"""H2 G8 切换演练配置：库固定为 ``smass_r22_g8_drill``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

G8_DB_NAME = os.environ.get('R22_G8_DB', 'smass_r22_g8_drill')

if not G8_DB_NAME.startswith('smass_r22_g8_'):
    raise RuntimeError(
        'G8 演练库名必须命中 smass_r22_g8_ 前缀，当前 {!r}'.format(G8_DB_NAME)
    )

DATABASES['default']['NAME'] = G8_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r22_g8_drill'
