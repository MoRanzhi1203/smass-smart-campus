"""G3 对象级授权：按角色收窄查询集（默认拒绝）。

原则（计划 G3）：
- 不依赖 UI 按钮或 URL 前缀，**服务层/查询集**本身就要收窄；
- 无角色 → 返回 ``none()``（默认拒绝，而不是"默认全量"）；
- 学院管理员/教师：只能看 ``scope_college`` 匹配的数据；scope 为空则拒绝（避免"空等于全部"的误判）；
- 学生：只能看自己。
"""
from r21_account.models import RoleCode, StudentProfile, TeacherProfile


def _active(account):
    if account is None or not getattr(account, 'is_authenticated', False):
        return []
    if not getattr(account, 'is_active', False):
        return []
    return account.active_roles()


def scoped_students(account):
    """返回该账号可见的学生档案查询集。"""
    qs = StudentProfile.objects.all()
    roles = _active(account)

    if not roles:
        return qs.none()

    if RoleCode.SYSTEM_ADMIN in roles:
        return qs

    if RoleCode.COLLEGE_ADMIN in roles or RoleCode.TEACHER in roles:
        scope = (getattr(account, 'scope_college', '') or '').strip()
        if not scope:
            return qs.none()
        return qs.filter(college_name=scope)

    if RoleCode.STUDENT in roles:
        return qs.filter(account=account)

    return qs.none()


def scoped_teachers(account):
    qs = TeacherProfile.objects.all()
    roles = _active(account)

    if not roles:
        return qs.none()
    if RoleCode.SYSTEM_ADMIN in roles:
        return qs
    if RoleCode.COLLEGE_ADMIN in roles:
        scope = (getattr(account, 'scope_college', '') or '').strip()
        if not scope:
            return qs.none()
        return qs.filter(college_name=scope)
    # 教师与学生默认不可见其他教师
    return qs.none()


def can_access_student(account, student_profile):
    """单个对象的归属判断（用于详情/编辑入口）。"""
    return scoped_students(account).filter(pk=student_profile.pk).exists()


def can_manage_roles(account):
    from r21_account.services import account_has_perm

    return account_has_perm(account, 'manage_roles')
