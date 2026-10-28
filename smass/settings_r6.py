"""R6 隔离配置：库 ``smass_r6_workflow``（全合成数据）。"""
import os

from .settings_r5 import *  # noqa: F401,F403

R6_DB_NAME = os.environ.get('R6_DB', 'smass_r6_workflow')

if not R6_DB_NAME.startswith('smass_r6_'):
    raise RuntimeError('R6 库名必须命中 smass_r6_ 前缀，当前 {!r}'.format(R6_DB_NAME))

DATABASES['default']['NAME'] = R6_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r6_workflow'

INSTALLED_APPS = list(INSTALLED_APPS) + ['smass_workflow.apps.SmassWorkflowConfig']

ROOT_URLCONF = 'smass.urls_r6'