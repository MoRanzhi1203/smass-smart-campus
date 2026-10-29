"""R10 隔离配置：库 ``smass_r10_release``（发行候选验收）。"""
import os

from .settings_r9 import *  # noqa: F401,F403

R10_DB_NAME = os.environ.get('R10_DB', 'smass_r10_release')

if not R10_DB_NAME.startswith('smass_r10_'):
    raise RuntimeError('R10 库名必须命中 smass_r10_ 前缀，当前 {!r}'.format(R10_DB_NAME))

DATABASES['default']['NAME'] = R10_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r10_release'

ROOT_URLCONF = 'smass.urls_r10'

# H3：MySQL 默认 REPEATABLE READ，会让 LiveServerTestCase 的服务器线程
# 在整个事务里看不到测试线程后来提交的行，导致 Django 自带的
# update_last_login 信号执行 `save(update_fields=['last_login'])` 时
# UPDATE 影响 0 行并抛 DatabaseError（表现为 /r21/login/ 500）。
# READ COMMITTED 让每个语句看到最新已提交数据，是 Django 官方推荐配置。
DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['init_command'] = (
    "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
)
