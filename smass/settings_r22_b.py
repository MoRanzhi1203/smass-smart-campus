"""G1-B：路径 B（正式切换 AUTH_USER_MODEL）的隔离实验配置。

用途：回答"在**保留 app01** 的前提下，把 AUTH_USER_MODEL 指向自定义用户模型
是否可行"，以及"已有数据的库能否中途切换"。

库名由环境变量 ``R22B_DB`` 控制，必须命中 ``smass_r22_`` 前缀：

    $env:R22B_DB = 'smass_r22_b_proto'     # 全新库从零迁移
    $env:R22B_DB = 'smass_r22_b_switch'    # 先按 auth.User 建库，再切换

刻意保留 ``app01``（这是与 R2.0 的 B 实验最大区别——R2.0 只验证了"全新项目"）。
"""
import os

from .settings import *  # noqa: F401,F403

R22B_DB_NAME = os.environ.get('R22B_DB', 'smass_r22_b_proto')

if not R22B_DB_NAME.startswith('smass_r22_'):
    raise RuntimeError(
        '路径 B 实验库名必须命中 smass_r22_ 前缀，当前 {!r}'.format(R22B_DB_NAME)
    )
if DATABASES['default']['NAME'] != 'smass':
    raise RuntimeError(
        '路径 B 实验只允许从开发库 smass 派生，当前 {!r}'.format(
            DATABASES['default']['NAME']
        )
    )

DATABASES['default']['NAME'] = R22B_DB_NAME

# 保留 app01（真实场景），并加入路径 B 的用户模型
INSTALLED_APPS = list(INSTALLED_APPS) + ['proto_user_model']

AUTH_USER_MODEL = 'proto_user_model.ProtoUser'

# 剥离对 app01 视图/中间件的运行时引用（模型仍可用）
ROOT_URLCONF = 'smass.urls_proto'
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith('app01.')]
