"""S18 隔离配置：库 ``smass_security_suite``（跨模块负向测试专用）。

装载 R12/R13/R14/R15/R17/R18/R19 与 S14/S16，用组合 URLConf 在同一测试库内
做 IDOR、越权、CSRF、XSS、SQLi、SSRF、并发重复等负向验证。
"""
import os

from .settings_r22 import *  # noqa: F401,F403

S18_DB_NAME = os.environ.get('S18_DB', 'smass_security_suite')

if not S18_DB_NAME.startswith('smass_security_'):
    raise RuntimeError('S18 库名必须命中 smass_security_ 前缀，当前 {!r}'.format(S18_DB_NAME))

DATABASES['default']['NAME'] = S18_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_security_suite'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_organization.apps.SmassOrganizationConfig',
    'smass_enrollment.apps.SmassEnrollmentConfig',
    'smass_attendance.apps.SmassAttendanceConfig',
    'smass_activities.apps.SmassActivitiesConfig',
    'smass_clubs.apps.SmassClubsConfig',
    'smass_forum.apps.SmassForumConfig',
    'smass_finance.apps.SmassFinanceConfig',
    'smass_party.apps.SmassPartyConfig',
    'smass_uploads.apps.SmassUploadsConfig',
    'smass_audit.apps.SmassAuditConfig',
    'smass_security_tests.apps.SmassSecurityTestsConfig',
]

ROOT_URLCONF = 'smass.urls_security'

SMASS_PRIVATE_MEDIA_ROOT = os.path.join(str(BASE_DIR), 'private_uploads')

LOGIN_URL = '/r21/login/'
