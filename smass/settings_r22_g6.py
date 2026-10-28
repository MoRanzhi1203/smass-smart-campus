"""R2.2 G6 性能基准配置：合成数据库（``smass_r22_g6_synth``）。

- 只允许 ``smass_r22_g6_`` 前缀；
- 全部数据由固定随机种子生成，**不含任何真实姓名/学号/手机号**；
- 正式 ``smass`` 只读，本配置从不指向它。
"""
import os

from .settings_r22 import *  # noqa: F401,F403

G6_DB_NAME = os.environ.get('R22_G6_DB', 'smass_r22_g6_synth')

if not G6_DB_NAME.startswith('smass_r22_g6_'):
    raise RuntimeError(
        'G6 基准库名必须命中 smass_r22_g6_ 前缀，当前 {!r}'.format(G6_DB_NAME)
    )

DATABASES['default']['NAME'] = G6_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r22_g6_synth'
