"""V2.1 仿真隔离配置：库 ``smass_simulation``（前缀硬校验）。

与 ``settings_product`` 的区别：注册仿真与宿舍两个新 app；其余业务 app、
URL、模板、中间件保持与产品一致。绝不指向 ``smass`` 或生产库。
"""
import os

from .settings_product import *  # noqa: F401,F403

SIM_DB_NAME = os.environ.get('SIM_DB', 'smass_simulation')

if not SIM_DB_NAME.startswith('smass_simulation'):
    raise RuntimeError(
        '仿真库名必须命中 smass_simulation 前缀，当前 {!r}'.format(SIM_DB_NAME))
if SIM_DB_NAME == 'smass':
    raise RuntimeError('仿真配置禁止指向正式库 smass')

DATABASES['default']['NAME'] = SIM_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_simulation'

INSTALLED_APPS = list(INSTALLED_APPS)
for _app in ('smass_simulation.apps.SmassSimulationConfig',
             'smass_dormitory.apps.SmassDormitoryConfig'):
    if _app not in INSTALLED_APPS:
        INSTALLED_APPS.append(_app)

# 仿真库不启用 MFA，避免批量走查被二次验证拦截
MFA_ENABLED = False

ROOT_URLCONF = 'smass.urls_product'
