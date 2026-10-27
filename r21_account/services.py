"""R2.1 服务层：角色/权限同步、登录限速、密码策略、审计、双写。

设计原则（对应计划 G2 "唯一写入权威"）：
- **角色授予**：``AccountRole`` 是记录，Django ``Group`` 是权限载体，两者在
  同一事务内同步，任何一侧失败都会回滚；
- **限速**：持久化在 ``LoginAttempt``，按 ``(login_name, ip)`` 与 ``(login_name)``
  两个维度统计，跨会话生效；
- **审计**：所有账号域敏感动作写 ``AccountAuditLog``，不记录密码/哈希。
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from r21_account import permissions as perms
from r21_account.models import (
    ROLE_TO_GROUP,
    Account,
    AccountAuditLog,
    AccountRole,
    LegacyAccountLink,
    LoginAttempt,
)

DEFAULT_RATE = {
    'window_seconds': 900,
    'max_per_login_ip': 5,
    'max_per_login': 20,
    'lock_seconds': 900,
}


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def audit(action, actor='', target='', detail='', ip=''):
    AccountAuditLog.objects.create(
        action=action, actor=actor[:32], target=target[:32],
        detail=detail[:255], ip=ip[:45],
    )


# ---------------------------------------------------------------------------
# 角色与权限
# ---------------------------------------------------------------------------
def account_content_type():
    return ContentType.objects.get_for_model(Account)


def ensure_role_groups():
    """幂等创建 4 个角色 Group，并按矩阵分配 Permission。"""
    content_type = account_content_type()
    created = {}

    for codename in perms.ACTION_CODENAMES:
        Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={'name': perms.CODENAME_LABELS.get(codename, codename)},
        )

    for role_code, group_name in ROLE_TO_GROUP.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        wanted = perms.ROLE_PERMISSIONS.get(str(role_code), set())
        perm_qs = Permission.objects.filter(
            content_type=content_type, codename__in=wanted
        )
        group.permissions.set(perm_qs)
        created[str(role_code)] = sorted(wanted)

    return created


def sync_account_groups(account):
    """把"未撤销的角色"同步为 Django Group 成员关系。"""
    active = account.active_roles()
    wanted_names = [ROLE_TO_GROUP[r] for r in active if r in ROLE_TO_GROUP]
    wanted_groups = list(Group.objects.filter(name__in=wanted_names))

    account.groups.set(wanted_groups)
    return wanted_names


def grant_role(account, role_code, granted_by='', ip=''):
    """授予角色（幂等）。同一事务内更新记录与 Group。"""
    with transaction.atomic():
        existing = AccountRole.objects.filter(
            account=account, role=role_code, revoked_at__isnull=True
        ).first()

        if existing is None:
            AccountRole.objects.create(
                account=account, role=role_code, granted_by=granted_by[:32]
            )
            audit('role_grant', actor=granted_by, target=account.login_name,
                  detail='role={}'.format(role_code), ip=ip)

        sync_account_groups(account)

    return account


def revoke_role(account, role_code, revoked_by='', ip=''):
    """撤销角色（保留历史记录，不物理删除）。"""
    with transaction.atomic():
        rows = AccountRole.objects.filter(
            account=account, role=role_code, revoked_at__isnull=True
        )
        if rows.exists():
            rows.update(revoked_at=timezone.now(), revoked_by=revoked_by[:32])
            audit('role_revoke', actor=revoked_by, target=account.login_name,
                  detail='role={}'.format(role_code), ip=ip)

        sync_account_groups(account)

    return account


def account_has_perm(account, codename):
    """统一入口：既支持 codename 也支持完整 'app.codename'。"""
    if '.' not in codename:
        codename = 'r21_account.{}'.format(codename)
    return bool(account and account.is_authenticated and account.has_perm(codename))


# ---------------------------------------------------------------------------
# 登录限速（持久化）
# ---------------------------------------------------------------------------
def _rate_config():
    return getattr(settings, 'R21_LOGIN_RATE_LIMIT', DEFAULT_RATE)


def register_login_result(login_name, ip, success):
    LoginAttempt.objects.create(login_name=login_name[:32], ip=(ip or '')[:45], success=success)
    if not success:
        audit('login_failed', target=login_name, ip=ip)


def login_lock_status(login_name, ip):
    """返回 ``(locked, remaining_seconds, reason)``。

    - 先看 ``(login_name, ip)`` 维度（防止恶意锁定他人：换 IP 才计数）；
    - 再看 ``(login_name)`` 维度（更高阈值，防分布式撞库）。
    """
    cfg = _rate_config()
    now = timezone.now()
    window_start = now - timedelta(seconds=cfg['window_seconds'])

    failures = LoginAttempt.objects.filter(
        login_name=login_name, success=False, created_at__gte=window_start
    )

    per_ip_qs = failures.filter(ip=(ip or '')[:45])
    if per_ip_qs.count() >= cfg['max_per_login_ip']:
        last = per_ip_qs.order_by('-created_at').first()
        return True, _remaining(last, cfg), 'per_login_ip'

    if failures.count() >= cfg['max_per_login']:
        last = failures.order_by('-created_at').first()
        return True, _remaining(last, cfg), 'per_login'

    return False, 0, ''


def _remaining(last_attempt, cfg):
    if last_attempt is None:
        return 0
    elapsed = (timezone.now() - last_attempt.created_at).total_seconds()
    return max(0, int(cfg['lock_seconds'] - elapsed))


def clear_login_failures(login_name):
    """成功登录后清理该账号的失败记录（不影响其他账号）。"""
    LoginAttempt.objects.filter(login_name=login_name, success=False).delete()


# ---------------------------------------------------------------------------
# 密码策略
# ---------------------------------------------------------------------------
def password_policy_errors(raw_password, account=None):
    if not raw_password:
        return ['密码不能为空']
    try:
        validate_password(raw_password, user=account)
    except ValidationError as exc:
        return list(exc.messages)
    return []


def set_temporary_password(account, raw_password):
    """设置一次性临时口令，并置 ``must_change_password=True``。"""
    account.set_password(raw_password)
    account.must_change_password = True
    account.save(update_fields=['password', 'must_change_password', 'password_changed_at'])
    audit('password_reset', target=account.login_name, detail='temporary password issued')
    return account


# ---------------------------------------------------------------------------
# 旧表映射
# ---------------------------------------------------------------------------
def link_legacy(account, source_table, source_pk, checksum=''):
    return LegacyAccountLink.objects.create(
        account=account,
        source_table=source_table,
        source_pk=str(source_pk),
        checksum=checksum,
    )
