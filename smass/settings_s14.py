"""S14 隔离配置：库 ``smass_s14_uploads``（全合成数据）。"""
import os

from .settings_r22 import *  # noqa: F401,F403

S14_DB_NAME = os.environ.get('S14_DB', 'smass_s14_uploads')

if not S14_DB_NAME.startswith('smass_s14_'):
    raise RuntimeError('S14 库名必须命中 smass_s14_ 前缀，当前 {!r}'.format(S14_DB_NAME))

DATABASES['default']['NAME'] = S14_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_s14_uploads'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_uploads.apps.SmassUploadsConfig',
]

ROOT_URLCONF = 'smass.urls_s14'

#: 私有上传目录（不经公共 MEDIA URL 暴露，下载必须走鉴权视图）
SMASS_PRIVATE_MEDIA_ROOT = os.path.join(str(BASE_DIR), 'private_uploads')

LOGIN_URL = '/r21/login/'
