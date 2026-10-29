"""H5 演练专用配置：允许 ``smass_h5_`` 前缀库。

继承 ``settings_r10``（含 READ COMMITTED、全部 R4-R10 应用），
仅放宽库名前缀限制，用于"现有 26 表结构 -> R10 升级 -> 备份恢复"演练。
"""
import os

from .settings_r10 import *  # noqa: F401,F403

H5_DB_NAME = os.environ.get('H5_DB', 'smass_h5_clone')

if not H5_DB_NAME.startswith('smass_h5_'):
    raise RuntimeError(
        'H5 演练库名必须命中 smass_h5_ 前缀，当前 {!r}'.format(H5_DB_NAME))

DATABASES['default']['NAME'] = H5_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_h5_clone'

# 演练库也是隔离库，同样用 READ COMMITTED，与生产建议一致
DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['init_command'] = (
    'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED'
)
