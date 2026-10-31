"""三端导航定义。

约定
----
- **导航名称使用业务语言**，不出现 R10/R20 等研发版本编号；
- 菜单是数据，不是模板硬编码：同一套 shell 按角色渲染不同导航；
- ``url_name`` 一律使用 ``workspace:`` 命名空间，深层业务页用 ``href`` 直接给出，
  避免把历史 ``r11_*`` 名字泄漏到用户界面。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str = ''
    href: str = ''
    icon: str = 'dot'
    badge_key: str = ''
    #: 需要系统管理员权限才能看到的项
    system_admin_only: bool = False


@dataclass(frozen=True)
class NavSection:
    label: str
    items: tuple


# ---------------------------------------------------------------------------
# 学生工作台
# ---------------------------------------------------------------------------
STUDENT_SECTIONS = (
    NavSection('我的学习', (
        NavItem('学习工作台', 'workspace:student_home', icon='home'),
        NavItem('我的课表', 'workspace:student_timetable', icon='calendar'),
        NavItem('我的课程', 'workspace:student_courses', icon='book'),
        NavItem('学籍信息', 'workspace:student_record', icon='file'),
    )),
    NavSection('日常事务', (
        NavItem('考勤与请假', 'workspace:student_attendance', icon='check'),
        NavItem('场地预约', 'workspace:student_bookings', icon='door'),
        NavItem('费用与账单', 'workspace:student_fees', icon='wallet'),
        NavItem('我的寝室', 'workspace:student_dormitory', icon='building'),
    )),
    NavSection('校园生活', (
        NavItem('活动与志愿', 'workspace:student_activities', icon='megaphone'),
        NavItem('社团', 'workspace:student_clubs', icon='users'),
        NavItem('学生组织', 'workspace:student_organizations', icon='shield'),
        NavItem('志愿服务', 'workspace:student_volunteer', icon='heart'),
    )),
    NavSection('消息', (
        NavItem('通知公告', 'workspace:student_notices', icon='bell'),
        NavItem('个人中心', 'workspace:profile', icon='settings'),
    )),
)

# ---------------------------------------------------------------------------
# 教师工作台
# ---------------------------------------------------------------------------
TEACHER_SECTIONS = (
    NavSection('教学工作', (
        NavItem('教学工作台', 'workspace:teacher_home', icon='home'),
        NavItem('我的课程', 'workspace:teacher_courses', icon='book'),
        NavItem('教学班', 'workspace:teacher_sections', icon='clipboard'),
        NavItem('我的课表', 'workspace:teacher_timetable', icon='calendar'),
    )),
    NavSection('学生事务', (
        NavItem('考勤管理', 'workspace:teacher_attendance', icon='check'),
        NavItem('学生事务', 'workspace:teacher_students', icon='users'),
        NavItem('审批中心', 'workspace:teacher_approvals', icon='inbox'),
    )),
    NavSection('消息', (
        NavItem('通知与公告', 'workspace:teacher_notices', icon='bell'),
        NavItem('个人中心', 'workspace:profile', icon='settings'),
    )),
)

#: 辅导员额外菜单（动态插入到"学生事务"分组之后）
COUNSELOR_SECTION = NavSection('辅导员工作', (
    NavItem('负责班级', 'workspace:teacher_classes', icon='building'),
    NavItem('负责学生', 'workspace:teacher_counselor_students', icon='users'),
    NavItem('请假审批', 'workspace:teacher_leave_review', icon='check'),
))

# ---------------------------------------------------------------------------
# 管理控制台
# ---------------------------------------------------------------------------
ADMIN_SECTIONS = (
    NavSection('总览', (
        NavItem('控制台总览', 'workspace:admin_home', icon='home'),
    )),
    NavSection('身份与组织', (
        NavItem('用户账号', 'workspace:admin_users', icon='users'),
        NavItem('角色与权限', 'workspace:admin_roles', icon='shield'),
        NavItem('组织架构', 'workspace:admin_organizations', icon='building'),
        NavItem('教师档案', 'workspace:admin_teachers', icon='users'),
    )),
    NavSection('学籍与教学', (
        NavItem('学籍管理', 'workspace:admin_records', icon='file'),
        NavItem('学籍异动', 'workspace:admin_record_changes', icon='inbox'),
        NavItem('学年学期与课程', 'workspace:admin_academics', icon='book'),
        NavItem('教学班与选课', 'workspace:admin_sections', icon='clipboard'),
    )),
    NavSection('排课与资源', (
        NavItem('排课与课表', 'workspace:admin_scheduling', icon='calendar'),
        NavItem('教室与场地', 'workspace:admin_facilities', icon='door'),
        NavItem('预约审批', 'workspace:admin_booking_approvals', icon='check'),
    )),
    NavSection('审批与工作流', (
        NavItem('待办与审批', 'workspace:admin_approvals', icon='inbox'),
        NavItem('流程定义', 'workspace:admin_workflows', icon='settings'),
    )),
    NavSection('校园业务', (
        NavItem('活动管理', 'workspace:admin_activities', icon='megaphone'),        NavItem('社团与学生组织', 'workspace:admin_clubs', icon='users'),
        NavItem('财务与账单', 'workspace:admin_finance', icon='wallet'),
        NavItem('通知公告', 'workspace:admin_notices', icon='bell'),
    )),
    NavSection('数据治理', (
        NavItem('数据质量', 'workspace:admin_data_quality', icon='shield'),
        NavItem('数据导入导出', 'workspace:admin_data_exchange', icon='file'),
    )),
    NavSection('运维与安全', (
        NavItem('运行监控', 'workspace:admin_monitoring', icon='chart'),
        NavItem('安全审计', 'workspace:admin_audit', icon='shield'),
        NavItem('系统配置', 'workspace:admin_settings', icon='settings',
                system_admin_only=True),
    )),
)


def sections_for(kind: str, account=None):
    """返回该端可见的导航分组（已过滤仅系统管理员的项）。"""
    if kind == 'student':
        return STUDENT_SECTIONS
    if kind == 'teacher':
        sections = list(TEACHER_SECTIONS)
        from . import permissions as perms
        if account is not None and perms.is_counselor(account):
            sections.insert(2, COUNSELOR_SECTION)
        return tuple(sections)
    if kind == 'admin':
        from . import permissions as perms
        system_admin = account is not None and perms.is_system_admin(account)
        if system_admin:
            return ADMIN_SECTIONS
        return tuple(
            NavSection(section.label, tuple(
                item for item in section.items if not item.system_admin_only))
            for section in ADMIN_SECTIONS
        )
    return ()


def nav_item_for(kind: str, url_name: str):
    for section in sections_for(kind):
        for item in section.items:
            if item.url_name == url_name:
                return item
    return None
