"""R11 隔离配置：库 ``smass_r11_scheduling``（全合成数据）。

R11 依赖 R16 的场地资源与 R5 的学期/教学班，因此继承 ``settings_r16``
（而 ``settings_r16`` 继承 ``settings_r22`` → 统一账号）。
"""
import os

from .settings_r16 import *  # noqa: F401,F403

R11_DB_NAME = os.environ.get('R11_DB', 'smass_r11_scheduling')

if not R11_DB_NAME.startswith('smass_r11_'):
    raise RuntimeError('R11 库名必须命中 smass_r11_ 前缀，当前 {!r}'.format(R11_DB_NAME))

DATABASES['default']['NAME'] = R11_DB_NAME
DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_smass_r11_scheduling'

INSTALLED_APPS = list(INSTALLED_APPS) + [
    'smass_academic.apps.SmassAcademicConfig',
    'smass_scheduling.apps.SmassSchedulingConfig',
]

# R11 需要 R5 的学期/教学班模型，因此其上层的 R5 app 必须存在
ROOT_URLCONF = 'smass.urls_r11'

R22_FLAGS = {
    'identity_mode': 'account',
    'route_policy_enabled': False,
    'audit_enabled': True,
    'dry_run': False,
    'legacy_bridge': False,
}

LOGIN_URL = '/r11/login/'

# ---------------------------------------------------------------------------
# R11 可配置策略（默认保守值，学校政策未定时可覆盖）
# ---------------------------------------------------------------------------
#: 不同教师类型的默认周课时上限（节）。
#: 注意：职称**只**影响这个上限，不授予任何额外权限。
SCHEDULING_WORKLOAD_CAPS = {
    'professor': 12,
    'associate_professor': 14,
    'lecturer': 16,
    'lab_teacher': 18,
    'admin_dual': 6,
    'visiting': 8,
}

#: 软约束权重（越小越优先）
SCHEDULING_WEIGHTS = {
    'prefer_hit': -12,
    'avoid_hit': 25,
    'same_room_bonus': -8,
    'gap_penalty': 6,
    'capacity_waste': 1,
    'instructor_type_bonus': -2,
}

#: 回溯预算
SCHEDULING_MAX_BACKTRACK = 400
