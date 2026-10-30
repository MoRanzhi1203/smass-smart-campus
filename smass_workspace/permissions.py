"""角色判定、工作台守卫与对象范围。

三条硬规则
----------
1. **登录后按角色落地**：管理端 > 教师端 > 学生端（同一账号可具备多角色）；
2. **越权不只隐藏菜单**：每个工作台视图都必须经过 ``require_kind``，后端直接 403；
3. **对象级范围**：辅导员只看自己负责的班级/学生，学院管理员只看本院，
   教师只看自己教学班的学生，学生只看自己。
"""
from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from r21_account.models import RoleCode
from smass_organization.models import (
    OrganizationMembership,
    OrganizationUnit,
    StudentRecord,
)

KIND_ADMIN = 'admin'
KIND_TEACHER = 'teacher'
KIND_STUDENT = 'student'

KIND_LABEL = {
    KIND_ADMIN: '管理控制台',
    KIND_TEACHER: '教师工作台',
    KIND_STUDENT: '学生工作台',
}

ROLE_LABEL = {
    RoleCode.SYSTEM_ADMIN: '系统管理员',
    RoleCode.COLLEGE_ADMIN: '学院管理员',
    RoleCode.TEACHER: '教师',
    RoleCode.STUDENT: '学生',
}

#: 辅导员在组织关系中的角色标识
COUNSELOR_ROLE = 'counselor'


# ---------------------------------------------------------------------------
# 身份
# ---------------------------------------------------------------------------
def is_authenticated(account) -> bool:
    return bool(getattr(account, 'is_authenticated', False))


def active_roles(account) -> set:
    if not is_authenticated(account):
        return set()
    try:
        return set(account.active_roles())
    except Exception:  # noqa: BLE001 - 角色表异常时不授予任何权限
        return set()


def is_system_admin(account) -> bool:
    if not is_authenticated(account):
        return False
    if getattr(account, 'is_superuser', False):
        return True
    return RoleCode.SYSTEM_ADMIN in active_roles(account)


def is_college_admin(account) -> bool:
    return RoleCode.COLLEGE_ADMIN in active_roles(account)


def is_admin(account) -> bool:
    """能否进入管理控制台。

    只认 ``system_admin`` / ``college_admin`` 角色（或 Django 超级用户）。
    ``is_staff`` 仅表示可进 Django 自带后台，**不构成**管理控制台授权，
    否则教师账号会被误判为管理员。
    """
    if not is_authenticated(account):
        return False
    return is_system_admin(account) or is_college_admin(account)


def is_teacher(account) -> bool:
    return RoleCode.TEACHER in active_roles(account)


def is_student(account) -> bool:
    return RoleCode.STUDENT in active_roles(account)


def allowed_kinds(account) -> set:
    kinds = set()
    if is_admin(account):
        kinds.add(KIND_ADMIN)
    if is_teacher(account):
        kinds.add(KIND_TEACHER)
    if is_student(account):
        kinds.add(KIND_STUDENT)
    return kinds


def landing_kind(account) -> str | None:
    """登录后默认落地端。"""
    kinds = allowed_kinds(account)
    for kind in (KIND_ADMIN, KIND_TEACHER, KIND_STUDENT):
        if kind in kinds:
            return kind
    return None


def landing_url(account) -> str:
    kind = landing_kind(account)
    if kind is None:
        return reverse('workspace:no_role')
    return reverse('workspace:{}_home'.format(kind))


# ---------------------------------------------------------------------------
# 辅导员与对象范围
# ---------------------------------------------------------------------------
def _active_memberships(account):
    if not is_authenticated(account):
        return OrganizationMembership.objects.none()
    return OrganizationMembership.objects.filter(
        account=account, ended_at__isnull=True)


def is_counselor(account) -> bool:
    """教师且被授予辅导员组织关系。"""
    if not is_teacher(account):
        return False
    return _active_memberships(account).filter(role=COUNSELOR_ROLE).exists()


def counselor_units(account):
    if not is_counselor(account):
        return OrganizationUnit.objects.none()
    unit_ids = list(_active_memberships(account).filter(
        role=COUNSELOR_ROLE).values_list('unit_id', flat=True))
    if not unit_ids:
        return OrganizationUnit.objects.none()
    # 班级下没有子节点，但保留子孙以支持"负责某专业/年级"的扩展
    units = list(OrganizationUnit.objects.filter(pk__in=unit_ids))
    collected = {}
    pending = list(units)
    while pending:
        unit = pending.pop()
        if unit.pk in collected:
            continue
        collected[unit.pk] = unit
        pending.extend(unit.children.all())
    return OrganizationUnit.objects.filter(
        pk__in=list(collected)).order_by('sort_order', 'code')


def counselor_classes(account):
    return counselor_units(account).filter(unit_type='class')


def counselor_students(account):
    units = counselor_units(account)
    if not units.exists():
        return StudentRecord.objects.none()
    return StudentRecord.objects.filter(unit__in=units)


def college_unit_ids(account) -> list:
    """学院管理员的范围（按 ``scope_college`` 匹配学院编码或名称）。"""
    code = (getattr(account, 'scope_college', '') or '').strip()
    if not code:
        return []
    roots = list(OrganizationUnit.objects.filter(code=code))
    if not roots:
        roots = list(OrganizationUnit.objects.filter(name=code))
    collected = {}
    pending = list(roots)
    while pending:
        unit = pending.pop()
        if unit.pk in collected:
            continue
        collected[unit.pk] = unit
        pending.extend(unit.children.all())
    return list(collected)


def scoped_student_records(account):
    """当前账号可见的学籍集合。"""
    if not is_authenticated(account):
        return StudentRecord.objects.none()
    if is_system_admin(account):
        return StudentRecord.objects.all()
    if is_college_admin(account):
        ids = college_unit_ids(account)
        return StudentRecord.objects.filter(unit_id__in=ids)
    if is_counselor(account):
        return counselor_students(account)
    # 教师：本人教学班内的学生
    from smass_academic.models import Enrollment, TeachingAssignment

    section_ids = list(TeachingAssignment.objects.filter(
        account=account, revoked_at__isnull=True).values_list(
        'section_id', flat=True))
    account_ids = list(Enrollment.objects.filter(
        section_id__in=section_ids).exclude(
        status='dropped').values_list('account_id', flat=True))
    return StudentRecord.objects.filter(account_id__in=account_ids)


# ---------------------------------------------------------------------------
# 守卫
# ---------------------------------------------------------------------------
def _login_redirect(request):
    next_url = request.get_full_path()
    login_url = settings.LOGIN_URL
    if '?' in login_url:
        return redirect('{}&next={}'.format(login_url, next_url))
    return redirect('{}?next={}'.format(login_url, next_url))


def require_kind(kind):
    """工作台入口守卫：未登录 → 登录页；无该端角色 → 后端 403。"""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            account = getattr(request, 'user', None)
            if not is_authenticated(account):
                return _login_redirect(request)
            if kind not in allowed_kinds(account):
                return render(request, 'workspace/403.html', {
                    'workspace_kind': None,
                    'attempted_kind': kind,
                    'attempted_label': KIND_LABEL.get(kind, kind),
                    'roles': [ROLE_LABEL.get(r, r) for r in sorted(active_roles(account))],
                    'landing_url': landing_url(account),
                }, status=403)
            request.workspace_kind = kind
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def require_system_admin(view):
    """管理端内的系统级页面：仅超级管理员，普通管理员后端 403。"""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        account = getattr(request, 'user', None)
        if not is_authenticated(account):
            return _login_redirect(request)
        if not is_system_admin(account):
            request.workspace_kind = KIND_ADMIN
            return render(request, 'workspace/403.html', {
                'workspace_kind': KIND_ADMIN,
                'attempted_kind': KIND_ADMIN,
                'attempted_label': '系统配置与权限治理',
                'roles': [ROLE_LABEL.get(r, r) for r in sorted(active_roles(account))],
                'landing_url': landing_url(account),
                'detail': '该页面仅系统管理员可访问。',
            }, status=403)
        request.workspace_kind = KIND_ADMIN
        return view(request, *args, **kwargs)

    return wrapper


def safe_next(request, default: str) -> str:
    """只接受站内 ``next``，防止开放重定向。"""
    candidate = request.GET.get('next') or request.POST.get('next') or ''
    if candidate and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        return candidate
    return default


def can_access_student(account, record) -> bool:
    """对象级校验：任意角色访问某学生档案前的唯一判定入口。"""
    if record is None:
        return False
    return scoped_student_records(account).filter(pk=record.pk).exists()
