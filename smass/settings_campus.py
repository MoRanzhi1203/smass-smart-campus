"""V2.2 统一校园业务库配置：``smass_campus`` 是唯一长期业务数据库。

继承 ``settings_product``（完整业务 app、URL、模板、MFA 语义），
仅替换数据库目标为 ``smass_campus``，并注册 V2.1 的生成器 app
（``smass_simulation``，用于批次与对象索引，不影响业务数据权威）。

其他旧库（smass_product_dev / smass_simulation / smass_unified_verify）
在本配置中**绝不被连接**。
"""
import os

from .settings_product import *  # noqa: F401,F403

CAMPUS_DB_NAME = os.environ.get('CAMPUS_DB', 'smass_campus')

if CAMPUS_DB_NAME != 'smass_campus':
    raise RuntimeError(
        '校园业务库名必须为 smass_campus，当前 {!r}'.format(CAMPUS_DB_NAME))
if CAMPUS_DB_NAME == 'smass':
    raise RuntimeError('校园配置禁止指向已删除的正式库 smass')

DATABASES['default']['NAME'] = CAMPUS_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_campus'

INSTALLED_APPS = list(INSTALLED_APPS)
for _app in ('smass_simulation.apps.SmassSimulationConfig',):
    if _app not in INSTALLED_APPS:
        INSTALLED_APPS.append(_app)

# 演示/校园环境默认关闭 MFA；生产按需开启（保持与产品一致的开关语义）
MFA_ENABLED = os.environ.get('SMASS_MFA_ENABLED', '0') == '1'

ROOT_URLCONF = 'smass.urls_product'
