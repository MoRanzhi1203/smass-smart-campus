"""G4 身份解析器：单一、确定性的五类解析。

权威依据是 ``LegacyAccountLink(source_table, source_pk)``。
**绝不**用登录名、角色提示、数字主键巧合或客户端参数来判定身份等价。

五类结果：
    legacy     仅旧身份（session['info'] 合法，无 Account）
    account    仅新身份（Account 活跃，无旧 session）
    dual       两者都有且 link 匹配
    conflict   两者都有但 link 缺失/不匹配 → 拒绝
    anonymous  都没有
"""
from dataclasses import dataclass

from app01.services.accounts import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER

KIND_LEGACY = 'legacy'
KIND_ACCOUNT = 'account'
KIND_DUAL = 'dual'
KIND_CONFLICT = 'conflict'
KIND_ANONYMOUS = 'anonymous'

#: session['info']['type'] -> LegacyAccountLink.source_table
LEGACY_ROLE_TO_TABLE = {
    ROLE_ADMIN: 'app01_admin',
    ROLE_TEACHER: 'app01_teacher',
    ROLE_STUDENT: 'app01_student',
}

VALID_LEGACY_ROLES = frozenset(LEGACY_ROLE_TO_TABLE)


@dataclass(frozen=True)
class Identity:
    kind: str
    account: object
    legacy: dict
    reason: str = ''

    @property
    def is_authenticated(self):
        return self.kind in (KIND_ACCOUNT, KIND_DUAL)

    @property
    def legacy_role(self):
        return (self.legacy or {}).get('type')

    @property
    def legacy_id(self):
        return (self.legacy or {}).get('id')


def _normalize_legacy(raw):
    """把 ``session['info']`` 规范化为可信的最小字典。

    只接受服务端写入过的 ``id`` / ``type`` / ``name``；未知 type 一律视为无效
    （防止伪造 session 内容被当作身份）。
    """
    if not isinstance(raw, dict):
        return None

    role = raw.get('type')
    legacy_id = raw.get('id')
    if role not in VALID_LEGACY_ROLES:
        return None
    if legacy_id is None or str(legacy_id).strip() == '':
        return None

    return {'id': str(legacy_id), 'type': role, 'name': raw.get('name') or ''}


def _resolve_legacy(request):
    try:
        raw = request.session.get('info')
    except Exception:  # noqa: BLE001 - 无 session 时不应崩溃
        return None
    return _normalize_legacy(raw)


def _unwrap(user):
    """把 Django 的 ``SimpleLazyObject`` 解包成真实模型实例。

    必要性：``request.user`` 是懒对象；若直接把它塞进 ``request.account``
    会形成双重 ``SimpleLazyObject``，导致 ``type()``/``is`` 判断失真。
    """
    from django.utils.functional import SimpleLazyObject

    if isinstance(user, SimpleLazyObject):
        user._setup()
        return user._wrapped
    return user


def _resolve_account(request):
    """只信任 ``request.user``；停用/异常一律返回 None（fail closed）。"""
    user = getattr(request, 'user', None)
    if user is None:
        return None

    from r21_account.models import Account

    user = _unwrap(user)

    if not isinstance(user, Account):
        return None
    if not getattr(user, 'is_active', False):
        return None
    if not getattr(user, 'is_authenticated', False):
        return None
    return user


def _link_matches(account, legacy):
    """用 LegacyAccountLink 判定两套身份是否指向同一个人。"""
    from r21_account.models import LegacyAccountLink

    table = LEGACY_ROLE_TO_TABLE.get(legacy['type'])
    if table is None:
        return False

    link = LegacyAccountLink.objects.filter(account=account).first()
    if link is None:
        return False

    return link.source_table == table and str(link.source_pk) == str(legacy['id'])


def resolve_identity(request):
    """五类解析的唯一入口。"""
    from r22_account import conf

    mode = conf.identity_mode()
    if mode == conf.IDENTITY_MODE_OFF:
        return Identity(KIND_ANONYMOUS, None, None, reason='mode_off')

    raw_user = getattr(request, 'user', None)
    account = _resolve_account(request)
    legacy = _resolve_legacy(request)

    # ---- 关键安全规则（fail closed）----
    # 存在"已认证但不是有效 Account"的用户（停用账号、或类型不是 Account），
    # 绝不能因此降级为 legacy 身份，否则等于用旧会话放大权限。
    user_authenticated = bool(getattr(raw_user, 'is_authenticated', False))
    if user_authenticated and account is None:
        if legacy is not None:
            return Identity(
                KIND_CONFLICT, None, legacy, reason='invalid_account_with_legacy'
            )
        return Identity(KIND_ANONYMOUS, None, None, reason='invalid_account')

    if mode == conf.IDENTITY_MODE_ACCOUNT:
        if account is None:
            return Identity(KIND_ANONYMOUS, None, None, reason='account_mode_no_account')
        return Identity(KIND_ACCOUNT, account, None)

    # dual 模式
    if account is not None and legacy is not None:
        if _link_matches(account, legacy):
            return Identity(KIND_DUAL, account, legacy)
        return Identity(KIND_CONFLICT, account, legacy, reason='link_mismatch')

    if account is not None:
        return Identity(KIND_ACCOUNT, account, None)

    if legacy is not None:
        return Identity(KIND_LEGACY, None, legacy)

    return Identity(KIND_ANONYMOUS, None, None)
