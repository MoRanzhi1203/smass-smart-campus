"""SMASS 产品配置：单一隔离库 ``smass_product_dev``，三端统一入口。

与 ``settings_integrated_dev`` 的区别
------------------------------------
- 这是**产品形态**（``/login/`` → 学生 / 教师 / 管理三端），不是研发门户；
- 库名独立（``smass_product_dev``），可随时删库重建；
- 复用 R4–R20 的全部业务 app、模型与服务，不新造第二套业务数据。

安全约束
--------
- 库名前缀硬校验，**绝不指向正式库 ``smass``**；
- 正式库只读：本配置只读正式库做历史迁移验证的源，从不写入。
"""
import os

from .settings_integrated_dev import *  # noqa: F401,F403

PRODUCT_DB_NAME = os.environ.get('PRODUCT_DB', 'smass_product_dev')

if not PRODUCT_DB_NAME.startswith('smass_product_dev'):
    raise RuntimeError(
        '产品库名必须命中 smass_product_dev 前缀，当前 {!r}'.format(
            PRODUCT_DB_NAME))
if PRODUCT_DB_NAME == 'smass':
    raise RuntimeError('产品配置禁止指向正式库 smass')

DATABASES['default']['NAME'] = PRODUCT_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_product_dev'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_workspace.apps.SmassWorkspaceConfig',
    'smass_mfa.apps.SmassMfaConfig',
    # V2.1 宿舍业务域（宿舍区/楼栋/寝室/床位/住宿/调宿/退宿/报修/巡查/宿管范围）
    'smass_dormitory.apps.SmassDormitoryConfig',
]

# MFA：默认关闭；设置 SMASS_MFA_ENABLED=1 后对系统管理员强制绑定与二次验证
MFA_ENABLED = os.environ.get('SMASS_MFA_ENABLED', '0') == '1'
MFA_REQUIRED_ROLES = ['system_admin']
MIDDLEWARE = list(MIDDLEWARE) + ['smass_mfa.middleware.MfaRequiredMiddleware']

ROOT_URLCONF = 'smass.urls_product'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'

# 三端 shell 的导航/角色上下文
TEMPLATES[0]['OPTIONS'].setdefault('context_processors', [])
if 'smass_workspace.context_processors.workspace' not in \
        TEMPLATES[0]['OPTIONS']['context_processors']:
    TEMPLATES[0]['OPTIONS']['context_processors'].append(
        'smass_workspace.context_processors.workspace')

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver', '*']

# 产品自检脚本以 stdout 输出 JSON；把控制台日志降到 WARNING，避免污染结果
LOGGING['handlers']['console']['level'] = 'WARNING'  # noqa: F405
LOGGING['root']['level'] = 'WARNING'  # noqa: F405
