"""路径 B 实验配置（隔离库 smass_proto_user_model）。

刻意**不安装 app01**：目的是"全新项目从零迁移"的基线实验，
与"给已有 4 个迁移的在用项目中途切换 AUTH_USER_MODEL"是两回事。

实测发现（已写入 ADR）：剥离 app01 后还必须同时处理两处耦合——
``ROOT_URLCONF`` 会 import ``app01.views``，``MIDDLEWARE`` 含
``app01.middleware.auth``。这两条正是"切换成本"的具体证据。
"""
from .settings import *  # noqa: F401,F403

B_PATH_DB_NAME = 'smass_proto_user_model'

if DATABASES['default']['NAME'] != 'smass':
    raise RuntimeError(
        '路径 B 实验只允许从开发库 smass 派生，当前 {!r}'.format(
            DATABASES['default']['NAME']
        )
    )

DATABASES['default']['NAME'] = B_PATH_DB_NAME

# 全新基线：只保留 Django 内置 app + 实验用的用户模型
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'proto_user_model',
]

# 剥离对 app01 的两处引用（否则 import 时报 app_label 缺失）
ROOT_URLCONF = 'smass.urls_proto'
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith('app01.')]

AUTH_USER_MODEL = 'proto_user_model.ProtoUser'
