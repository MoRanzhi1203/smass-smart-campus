"""PMR 演练专用配置：允许 ``smass_pmr_target_`` 前缀库。

继承 ``settings_r10``（含 READ COMMITTED、全部 R4-R10 应用），
仅放宽库名前缀限制，用于"合成旧库 -> R10 目标库"的行迁移演练。

与 ``settings_h5`` 的区别：
- H5 用于"结构升级"（26 -> 72 表）
- PMR 用于"行迁移"（在全新 R10 库里接收合成旧行）

源库（``smass_pmr_*``）不通过 Django 访问，只由脚本用原生连接只读。
"""
import os

from .settings_r10 import *  # noqa: F401,F403

PMR_DB_NAME = os.environ.get('PMR_DB', 'smass_pmr_target')

if not PMR_DB_NAME.startswith('smass_pmr_target_'):
    raise RuntimeError(
        'PMR 目标库名必须命中 smass_pmr_target_ 前缀，当前 {!r}'.format(PMR_DB_NAME))

DATABASES['default']['NAME'] = PMR_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_pmr_target'

DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['init_command'] = (
    'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED'
)
