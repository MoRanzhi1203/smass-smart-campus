"""G1-B 对照配置：与 settings_r22_b 相同的库，但 AUTH_USER_MODEL 仍是 ``auth.User``。

用途：先把 ``smass_r22_b_switch`` 建成"标准 Django 项目"（有 auth_user 表与真实数据），
再用 ``settings_r22_b`` 指向同一个库，观察**中途切换**会发生什么。

注意：这里**不安装** ``proto_user_model``。
实测原因：`ProtoUser` 继承 `PermissionsMixin`，其 `groups`/`user_permissions`
的反向访问器默认是 `user_set`，与 `auth.User` 冲突 → `fields.E304`。
这也正是路径 B 在"切换期"必须额外处理的成本之一。
"""
import os

from .settings import *  # noqa: F401,F403

R22B_DB_NAME = os.environ.get('R22B_DB', 'smass_r22_b_switch')

if not R22B_DB_NAME.startswith('smass_r22_'):
    raise RuntimeError('实验库名必须命中 smass_r22_ 前缀，当前 {!r}'.format(R22B_DB_NAME))

DATABASES['default']['NAME'] = R22B_DB_NAME

ROOT_URLCONF = 'smass.urls_proto'
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith('app01.')]
