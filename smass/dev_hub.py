"""集成开发统一入口：按角色展示可进入的模块（R10 管理 + R11–R20 业务）。

注意：本模块只服务于 ``smass.settings_integrated_dev``，不参与正式默认入口，
也不改变任何现有 URL 名称与认证状态。

角色体系（来自 ``r21_account.models.RoleCode``）只有四种：
``system_admin`` / ``college_admin`` / ``teacher``（含辅导员）/ ``student``。

同一模块对不同角色可能指向不同页面（例如 R11：管理员看排课规划，教师看教师课表，
学生看学生课表），因此卡片支持 ``role_urls`` 覆盖。
"""
from __future__ import annotations

from django.shortcuts import redirect, render

from r21_account import authorization as authz
from r21_account.models import RoleCode

ADMIN = 'admin'
TEACHER = 'teacher'
STUDENT = 'student'

#: (分组, 模块名, 默认入口, 说明, 角色专属入口)
CARDS = (
    ('统一管理后台', 'R10 管理与运维', '/r10/',
     '组织/学籍、教务、流程、分析、API、运维的统一后台首页', None),
    ('统一管理后台', 'R4 组织与学籍', '/r4/import/',
     '学院/专业/班级、学籍档案、导入与导出', None),
    ('统一管理后台', 'R6 流程审批', '/r6/tasks/',
     '待办、流程实例、审批动作与通知', None),
    ('统一管理后台', 'R7 数据看板', '/r7/dashboard/',
     '指标、报表与导出', None),
    ('统一管理后台', 'R9 运维状态', '/r9/status/',
     '发布与运维状态', None),
    ('教学与教务', 'R5 学年学期课程', '/r5/enroll/',
     '学年、学期、课程、教学班、选课', None),
    ('教学与教务', 'R11 排课与课表', '/r11/plan/',
     '排课规划、冲突检测、学生/教师/教室三张课表',
     {TEACHER: '/r11/timetable/teacher/',
      STUDENT: '/r11/timetable/student/'}),
    ('学工与学生事务', 'R12 自动分班与学籍异动', '/r12/placement/',
     '分班规则、预演、执行与回滚；转专业与学籍异动', None),
    ('学工与学生事务', 'R13 签到考勤与请销假', '/r13/sessions/',
     '签到、请假、补签、统计', None),
    ('学工与学生事务', 'R14 第二课堂与志愿', '/r14/activities/',
     '活动、报名、志愿时长、学分认定', None),
    ('团学组织', 'R15 团委/学生会/社团', '/r15/clubs/',
     '社团、任职、活动与公告', None),
    ('资源与服务', 'R16 场地预约', '/r16/rooms/',
     '教室/场地台账、预约与审批', None),
    ('资源与服务', 'R17 论坛与公告', '/r17/forum/',
     '板块、帖子、公告、举报处理', None),
    ('资源与服务', 'R18 学费与账单', '/r18/bills/',
     '账单、台账、受控退费', None),
    ('党建与专项', 'R19 党建与专项组织', '/r19/orgs/',
     '组织、成员、文档与访问控制', None),
    ('门户', 'R20 多角色门户', '/r20/',
     '学生/教师/辅导员/管理员的统一门户视图', None),
)

#: 需要管理类权限的入口（非管理员进入会灰显；页面内部仍有二次校验）
_ADMIN_ONLY_PREFIXES = ('/r10/', '/r9/', '/r7/', '/r6/tasks/', '/r5/enroll/',
                        '/r12/placement/')

#: 学生端不可进入的入口（学生只能看自己的课表/考勤/账单/活动）
_STUDENT_DENY_PREFIXES = ('/r10/', '/r9/', '/r7/', '/r6/tasks/', '/r5/enroll/',
                          '/r12/placement/', '/r19/')


def _label(roles):
    names = {
        RoleCode.SYSTEM_ADMIN: '系统管理员',
        RoleCode.COLLEGE_ADMIN: '学院管理员',
        RoleCode.TEACHER: '教师/辅导员',
        RoleCode.STUDENT: '学生',
    }
    return [names.get(item, item) for item in roles] or ['未分配角色']


def _actor_kind(roles, is_admin):
    if is_admin:
        return ADMIN
    if RoleCode.STUDENT in roles:
        return STUDENT
    if RoleCode.TEACHER in roles:
        return TEACHER
    return TEACHER


def hub(request):
    """统一首页：未登录跳统一登录，登录后按角色渲染模块卡片。"""
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return redirect('/r21/login/?next=/hub/')

    roles = sorted(authz.active_roles(user))
    is_admin = bool({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN} & set(roles)) \
        or authz.has_action(user, 'manage_roles')
    kind = _actor_kind(roles, is_admin)

    cards = []
    for group, name, url, desc, role_urls in CARDS:
        target = url
        if role_urls and kind in role_urls:
            target = role_urls[kind]

        if is_admin:
            enabled, reason = True, ''
        elif kind == STUDENT:
            enabled = not url.startswith(_STUDENT_DENY_PREFIXES)
            reason = '' if enabled else '学生端不可用'
        else:
            enabled = not url.startswith(_ADMIN_ONLY_PREFIXES)
            reason = '' if enabled else '需要管理员权限'
        cards.append({'group': group, 'name': name, 'url': target,
                      'desc': desc, 'enabled': enabled, 'reason': reason})

    groups = []
    for card in cards:
        if not groups or groups[-1]['name'] != card['group']:
            groups.append({'name': card['group'], 'cards': []})
        groups[-1]['cards'].append(card)

    return render(request, 'dev_hub/index.html', {
        'account': user,
        'roles': _label(roles),
        'is_admin': is_admin,
        'kind': kind,
        'groups': groups,
    })
