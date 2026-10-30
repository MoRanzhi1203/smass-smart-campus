"""演示/本地查看配置：库 ``smass_demo``（正式库 ``smass`` 的只读副本）。

用途：让评审者在**不触碰正式库**的前提下浏览真实数据页面。

- 建库方式：`mysqldump smass` → 导入 `smass_demo`（只读导出，不改正式库）；
- 本配置只允许 ``smass_demo``，防止误连正式库；
- ``DEBUG`` 打开、``ALLOWED_HOSTS`` 放开，仅用于本机演示，禁止用于生产。
"""
import os

from .settings import *  # noqa: F401,F403

DEMO_DB_NAME = os.environ.get('DEMO_DB', 'smass_demo')

if DEMO_DB_NAME != 'smass_demo':
    raise RuntimeError('演示配置只允许 smass_demo，当前 {!r}'.format(DEMO_DB_NAME))

DATABASES['default']['NAME'] = DEMO_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_demo'

DEBUG = True
ALLOWED_HOSTS = ['*']
