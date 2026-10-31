"""统一数据库验证环境配置：``smass_unified_verify``。

用途
----
- 以产品新模型为准，从零执行完整迁移，验证结构、约束与初始化；
- 承载旧数据迁移演练（只从正式库只读读取）；
- 可随时删除重建，与 ``smass_product_dev``、正式库 ``smass`` 完全隔离。

安全
----
- 库名前缀硬校验 ``smass_unified_verify``，绝不指向正式库或产品开发库；
- 本配置只用于验证与演练，不作为生产配置。
"""
import os

from .settings_product import *  # noqa: F401,F403

UNIFIED_DB_NAME = os.environ.get('UNIFIED_DB', 'smass_unified_verify')

if not UNIFIED_DB_NAME.startswith('smass_unified_verify'):
    raise RuntimeError(
        '统一验证库必须命中 smass_unified_verify 前缀，当前 {!r}'.format(
            UNIFIED_DB_NAME))
if UNIFIED_DB_NAME in ('smass', 'smass_product_dev'):
    raise RuntimeError('统一验证库禁止指向正式库或产品开发库')

DATABASES['default']['NAME'] = UNIFIED_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_unified_verify'

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
