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

# PMR 演练会产生三类库：
#   smass_pmr_target_*   行迁移 / 双写目标
#   smass_pmr_upg_*      升级演练
#   smass_pmr_restore_*  备份恢复验证
# 三者都需要 Django 能连，因此都放行；仍严格禁止指向正式 smass 或其他前缀。
ALLOWED_PMR_PREFIXES = (
    'smass_pmr_target_',
    'smass_pmr_upg_',
    'smass_pmr_restore_',
)

if not PMR_DB_NAME.startswith(ALLOWED_PMR_PREFIXES):
    raise RuntimeError(
        'PMR 库名必须命中 {} 之一，当前 {!r}'.format(
            ALLOWED_PMR_PREFIXES, PMR_DB_NAME))

DATABASES['default']['NAME'] = PMR_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_pmr_target'

DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['init_command'] = (
    'SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED'
)
