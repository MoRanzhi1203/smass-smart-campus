"""S06 统一授权门面：默认拒绝的五维授权。

主任务书 S06 要求授权在 **service / UI / API / query / report / import / export**
各层一致，并覆盖：RBAC、组织域、对象级、字段级、业务状态。

设计约束
--------
1. **默认拒绝**：无角色、无规则、未知资源、未知状态转换，一律拒绝。
2. **单一门面**：所有层都调用本模块，不在各视图里各写一套判断
   （避免"页面挡住了但 API 没挡"这类经典漏洞）。
3. **组织域收窄发生在查询集层面**：返回的是已经过滤的 QuerySet，
   不是"先查全量再在 Python 里过滤"——后者容易被忘记。
4. **字段级用允许列表**：未列入允许列表的字段不出现（而不是"黑名单删除"），
   新增字段默认不可见，符合 fail-closed。
5. **业务状态转换可配置**：默认只允许最小规则；学校政策未定的部分
   用 ``BUSINESS_CONFIG_PENDING`` 标注，并保持默认拒绝。

与既有代码的关系：``r21_account/scoping.py`` 保持不动（它承担 student/teacher
两类档案的收窄）；本模块在其上提供统一 API，并把字段级与状态级补齐。
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from r21_account.models import RoleCode
from r21_account.services import account_has_perm

# ---------------------------------------------------------------------------
# 通用常量
# ---------------------------------------------------------------------------
ALL_FIELDS = '*'


class AuthzDenied(PermissionError):
    """授权拒绝。

    调用方（service / view）应把它转成统一的 403，而不是 500；
    消息里**不得**包含被拒绝对象的敏感字段值。
    """

    def __init__(self, reason, *, action='', resource='', detail=''):
        self.reason = reason
        self.action = action
        self.resource = resource
        self.detail = detail
        parts = [reason]
        if resource:
            parts.append('resource={}'.format(resource))
        if action:
            parts.append('action={}'.format(action))
        if detail:
            # detail 只放字段名/原因码，绝不放字段值
            parts.append('detail={}'.format(detail))
        super().__init__(' '.join(parts))


# ---------------------------------------------------------------------------
# 资源注册表
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResourceSpec:
    """一个受保护资源的授权元数据。"""

    name: str
    model: str                     # 'app_label.ModelName'
    scope_field: str = ''          # 组织域字段（如 college_name）
    owner_field: str = ''          # 对象归属字段（如 account）
    states: tuple = ()             # 业务状态集合（空 = 无状态机）
    state_field: str = 'status'


RESOURCES = {
    'student': ResourceSpec(
        name='student',
        model='r21_account.StudentProfile',
        scope_field='college_name',
        owner_field='account',
        states=('active', 'suspended', 'graduated', 'withdrawn'),
        state_field='status',
    ),
    'teacher': ResourceSpec(
        name='teacher',
        model='r21_account.TeacherProfile',
        scope_field='college_name',
        owner_field='account',
    ),
    'account': ResourceSpec(
        name='account',
        model='r21_account.Account',
        scope_field='scope_college',
        owner_field='pk',
    ),
}

#: 动作 -> 需要的 Django permission codename（None 表示仅靠对象/字段规则）
ACTION_PERMISSIONS = {
    'view': 'view_data',
    'create': 'add_data',
    'update': 'change_data',
    'delete': 'delete_data',
    'import': 'import_data',
    'export': 'view_data',
    'reset_password': 'reset_password',
    'manage_roles': 'manage_roles',
    'bulk_delete': 'dangerous_bulk_delete',
}

# ---------------------------------------------------------------------------
# 字段级：允许列表（未列出的字段一律不可见）
# ---------------------------------------------------------------------------
#: (resource, role) -> 允许的字段集合；ALL_FIELDS 表示全部
FIELD_ALLOW = {
    ('student', RoleCode.SYSTEM_ADMIN): ALL_FIELDS,
    ('student', RoleCode.COLLEGE_ADMIN): ALL_FIELDS,
    ('student', RoleCode.TEACHER): frozenset({
        'student_no', 'name', 'college_name', 'classes_name'}),
    ('student', RoleCode.STUDENT): frozenset({
        'student_no', 'name', 'college_name', 'classes_name', 'phone'}),

    ('teacher', RoleCode.SYSTEM_ADMIN): ALL_FIELDS,
    ('teacher', RoleCode.COLLEGE_ADMIN): ALL_FIELDS,
    ('teacher', RoleCode.TEACHER): frozenset({
        'teacher_no', 'name', 'college_name'}),
    ('teacher', RoleCode.STUDENT): frozenset({'teacher_no', 'name', 'college_name'}),

    ('account', RoleCode.SYSTEM_ADMIN): frozenset({
        'id', 'login_name', 'display_name', 'person_type', 'is_active',
        'must_change_password', 'scope_college', 'last_login', 'created_at'}),
    ('account', RoleCode.COLLEGE_ADMIN): frozenset({
        'id', 'login_name', 'display_name', 'person_type', 'is_active', 'scope_college'}),
    ('account', RoleCode.TEACHER): frozenset({'id', 'login_name', 'display_name', 'person_type'}),
    ('account', RoleCode.STUDENT): frozenset({'id', 'login_name', 'display_name', 'person_type'}),
}

#: 需要脱敏呈现的字段（即使可见也不返回原值）
MASKED_FIELDS = {
    'card_id': lambda v: _mask(v, keep_head=3, keep_tail=2),
    'phone': lambda v: _mask(v, keep_head=3, keep_tail=2),
    'password': lambda v: '***',
}

#: 只有这些角色可以拿到未脱敏的敏感字段
UNMASKED_ROLES = frozenset({RoleCode.SYSTEM_ADMIN})


def _mask(value, keep_head=3, keep_tail=2):
    if value is None:
        return None
    text = str(value)
    if len(text) <= keep_head + keep_tail:
        return '*' * len(text)
    return text[:keep_head] + '*' * (len(text) - keep_head - keep_tail) + text[-keep_tail:]


# ---------------------------------------------------------------------------
# 业务状态机（默认最小规则；未知转换一律拒绝）
# ---------------------------------------------------------------------------
#: resource -> {from_state: {action: allowed_roles}}
DEFAULT_TRANSITIONS = {
    'student': {
        'active': {'suspend': {RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN},
                   'graduate': {RoleCode.SYSTEM_ADMIN}},
        'suspended': {'reinstate': {RoleCode.SYSTEM_ADMIN}},
        'graduated': {},          # 终态：默认不允许再转换
        'withdrawn': {},          # 终态
    },
}

#: 未在 DEFAULT_TRANSITIONS 中定义时是否允许（默认拒绝）
UNKNOWN_TRANSITION_ALLOWED = False


def transitions():
    """合并 settings 覆盖与默认规则。"""
    cfg = {k: {s: dict(a) for s, a in v.items()} for k, v in DEFAULT_TRANSITIONS.items()}
    override = getattr(settings, 'AUTHORIZATION_TRANSITIONS', None) or {}
    for resource, table in override.items():
        cfg.setdefault(resource, {})
        for state, actions in table.items():
            cfg[resource].setdefault(state, {}).update(actions)
    return cfg


# ---------------------------------------------------------------------------
# 基础判定
# ---------------------------------------------------------------------------
def active_roles(account):
    """账号当前有效角色集合（停用/匿名返回空集）。"""
    if account is None:
        return frozenset()
    if not getattr(account, 'is_authenticated', False):
        return frozenset()
    if not getattr(account, 'is_active', False):
        return frozenset()
    try:
        return frozenset(account.active_roles())
    except Exception:  # noqa: BLE001 - 兼容非 r21 Account（如匿名用户）
        return frozenset()


def has_action(account, action):
    """RBAC 判定：动作 -> Django permission。未知动作默认拒绝。"""
    codename = ACTION_PERMISSIONS.get(action)
    if codename is None:
        return False
    return account_has_perm(account, codename)


def require_action(account, action):
    if not has_action(account, action):
        raise AuthzDenied('action_forbidden', action=action)
    return True


# ---------------------------------------------------------------------------
# 组织域 / 对象级
# ---------------------------------------------------------------------------
def _spec(resource):
    spec = RESOURCES.get(resource)
    if spec is None:
        raise AuthzDenied('unknown_resource', resource=resource)
    return spec


def _model(resource):
    from django.apps import apps

    app_label, model_name = _spec(resource).model.split('.')
    return apps.get_model(app_label, model_name)


def scope_queryset(account, resource, qs=None):
    """返回按组织域收窄后的 QuerySet（默认拒绝 = 空集）。"""
    spec = _spec(resource)
    qs = qs if qs is not None else _model(resource).objects.all()
    roles = active_roles(account)

    if not roles:
        return qs.none()
    if RoleCode.SYSTEM_ADMIN in roles:
        return qs

    if RoleCode.COLLEGE_ADMIN in roles or RoleCode.TEACHER in roles:
        scope = (getattr(account, 'scope_college', '') or '').strip()
        if not scope or not spec.scope_field:
            # 空 scope 不等于"全部"：拒绝，避免最大权限默认值
            return qs.none()
        return qs.filter(**{spec.scope_field: scope})

    if RoleCode.STUDENT in roles:
        if spec.owner_field == 'pk':
            return qs.filter(pk=account.pk)
        if not spec.owner_field:
            return qs.none()
        return qs.filter(**{spec.owner_field: account})

    return qs.none()


def can_access_object(account, resource, obj):
    """对象级判定：该对象是否落在调用者的可见集合内。"""
    if obj is None:
        return False
    spec = _spec(resource)
    if not active_roles(account):
        return False
    return scope_queryset(account, resource).filter(pk=obj.pk).exists()


def require_object(account, resource, obj, action='view'):
    """对象级 + RBAC 双检；任一不通过即拒绝（防 IDOR）。"""
    if obj is None:
        raise AuthzDenied('object_missing', action=action, resource=resource)
    if not has_action(account, action):
        raise AuthzDenied('action_forbidden', action=action, resource=resource)
    if not can_access_object(account, resource, obj):
        raise AuthzDenied('object_out_of_scope', action=action, resource=resource)
    return True


# ---------------------------------------------------------------------------
# 字段级
# ---------------------------------------------------------------------------
def visible_fields(account, resource):
    """该角色对该资源可见的字段集合（frozenset 或 ALL_FIELDS）。"""
    roles = active_roles(account)
    if not roles:
        return frozenset()
    allowed = set()
    for role in roles:
        spec = FIELD_ALLOW.get((resource, role))
        if spec == ALL_FIELDS:
            return ALL_FIELDS
        if spec:
            allowed |= set(spec)
    return frozenset(allowed)


def can_view_field(account, resource, field):
    allowed = visible_fields(account, resource)
    if allowed == ALL_FIELDS:
        return True
    return field in allowed


def redact(account, resource, data, obj=None):
    """按字段可见性裁剪 + 敏感字段脱敏。

    ``data`` 是 dict（通常来自 ``.values()`` 或序列化结果）。
    返回新 dict；**未允许的键直接消失**，敏感字段在非特权角色下被掩码。
    """
    allowed = visible_fields(account, resource)
    if allowed == frozenset():
        return {}

    roles = active_roles(account)
    may_see_raw = bool(roles & UNMASKED_ROLES)

    out = {}
    for key, value in (data or {}).items():
        if allowed != ALL_FIELDS and key not in allowed:
            continue
        if key in MASKED_FIELDS and not may_see_raw:
            out[key] = MASKED_FIELDS[key](value)
        else:
            out[key] = value
    return out


def writable_fields(account, resource, action='update'):
    """可写字段 = 可见字段（默认拒绝，新增字段默认不可写）。"""
    if not has_action(account, action):
        return frozenset()
    return visible_fields(account, resource)


def check_write_fields(account, resource, fields, action='update'):
    """返回被拒绝的字段名列表（空列表表示全部允许）。"""
    allowed = writable_fields(account, resource, action)
    if allowed == ALL_FIELDS:
        return []
    return sorted(set(fields) - set(allowed))


def require_write_fields(account, resource, fields, action='update'):
    denied = check_write_fields(account, resource, fields, action)
    if denied:
        raise AuthzDenied('field_forbidden', action=action, resource=resource,
                          detail=','.join(denied))
    return True


# ---------------------------------------------------------------------------
# 业务状态
# ---------------------------------------------------------------------------
def current_state(obj, resource):
    spec = _spec(resource)
    if not spec.states:
        return None
    return getattr(obj, spec.state_field, None)


def can_transition(account, resource, obj, action):
    """业务状态转换判定。未知资源/状态/动作一律拒绝。"""
    spec = _spec(resource)
    if not spec.states:
        return False  # 该资源没有状态机 -> 不允许状态转换
    state = current_state(obj, resource)
    if state is None:
        return False
    table = transitions().get(resource) or {}
    actions = table.get(state)
    if actions is None:
        return UNKNOWN_TRANSITION_ALLOWED
    roles = actions.get(action)
    if roles is None:
        return UNKNOWN_TRANSITION_ALLOWED
    return bool(active_roles(account) & set(roles))


def require_transition(account, resource, obj, action):
    if not can_transition(account, resource, obj, action):
        raise AuthzDenied('transition_forbidden', action=action, resource=resource)
    return True


# ---------------------------------------------------------------------------
# 诊断（不泄露数据，只描述能力）
# ---------------------------------------------------------------------------
def _fields_desc(account, resource):
    allowed = visible_fields(account, resource)
    if allowed == ALL_FIELDS:
        return ['*']
    return sorted(allowed)


def describe(account):
    roles = sorted(active_roles(account))
    return {
        'authenticated': bool(getattr(account, 'is_authenticated', False)),
        'active': bool(getattr(account, 'is_active', False)),
        'roles': roles,
        'scope_college': (getattr(account, 'scope_college', '') or '') or None,
        'actions': {a: has_action(account, a) for a in sorted(ACTION_PERMISSIONS)},
        'visible_fields': {r: _fields_desc(account, r) for r in RESOURCES},
    }
