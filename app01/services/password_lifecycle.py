"""S02 密码生命周期服务。

覆盖主任务书 S02 的验收点：

1. 遗留哈希账号按**可配置策略**强制重置（默认 OFF）；
2. 停用账号按可配置策略强制重置（默认 OFF）；
3. 管理员临时重置流程：一次性口令 + 必须改密 + 到期时间 + 审计；
4. 密码校验器在真实写入路径生效（复用 Django validators）；
5. 改密/重置后**旧会话立即失效**（会话世代 epoch 机制）；
6. 限速与审计（复用 ``app01.services.accounts`` 的登录限速与审计通道）。

设计要点
--------
* 策略来自 ``settings.PASSWORD_LIFECYCLE``，**全部默认关闭**，符合"策略可配置、
  默认 OFF"的要求；学校政策未定时不需要改代码。
* 状态存在 ``app01.AccountSecurityState`` 独立表。若该表尚未在当前数据库落地
  （例如正式 ``smass`` 库保持只读、未应用迁移），所有函数**降级为安全空操作**，
  绝不抛异常导致 500——避免"上了代码就必须先迁库"的硬依赖。
* 从不读取、不记录明文口令与哈希；审计只写账号标识与事件类型。
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app01.services import accounts

logger = logging.getLogger('smass.audit')

#: 策略默认值：全部关闭，等待学校政策确认
POLICY_DEFAULTS = {
    'ENABLED': False,                    # 总开关；关闭时中间件不拦截
    'FORCE_RESET_LEGACY': False,         # 仍持有 32 位 MD5 的账号强制改密
    'FORCE_RESET_INACTIVE': False,       # 停用账号强制改密
    'MAX_AGE_DAYS': 0,                   # 0 = 不按时间强制
    'TEMP_PASSWORD_TTL_MINUTES': 1440,   # 一次性口令默认 24 小时
    'DETECT_LEGACY_ON_LOGIN': True,      # 登录时自动识别并登记遗留哈希
}

TABLE_NAME = 'app01_account_security_state'

#: 表可用性缓存（首次探测后固定；测试/迁移后可 force 刷新）
_TABLE_PROBE = {'known': False, 'available': False}


def policy():
    """返回合并后的策略字典（settings 覆盖默认值）。"""
    cfg = dict(POLICY_DEFAULTS)
    cfg.update(getattr(settings, 'PASSWORD_LIFECYCLE', None) or {})
    return cfg


def lifecycle_enabled():
    return bool(policy()['ENABLED'])


def table_available(force=False):
    """探测状态表是否存在。缺表不是错误，只是"策略未落地"。"""
    if _TABLE_PROBE['known'] and not force:
        return _TABLE_PROBE['available']
    from django.db import connection

    available = False
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1 FROM {} LIMIT 1'.format(TABLE_NAME))
            cur.fetchone()
        available = True
    except Exception:  # noqa: BLE001 - 缺表/权限问题都降级
        available = False
    _TABLE_PROBE.update(known=True, available=available)
    return available


def reset_table_probe():
    """测试辅助：强制下次重新探测。"""
    _TABLE_PROBE.update(known=False, available=False)


# ---------------------------------------------------------------------------
# 状态读写
# ---------------------------------------------------------------------------
def _model():
    from app01.models import AccountSecurityState

    return AccountSecurityState


def get_state(account_type, account_id):
    """取状态行；缺表或不存在均返回 ``None``。"""
    if not table_available():
        return None
    return _model().objects.filter(
        account_type=account_type, account_id=str(account_id)).first()


def get_or_create_state(account_type, account_id, **defaults):
    """取或建状态行；缺表返回 ``None``。"""
    if not table_available():
        return None
    state, _created = _model().objects.get_or_create(
        account_type=account_type,
        account_id=str(account_id),
        defaults=defaults or None,
    )
    return state


def _save(state, fields):
    if state is None:
        return None
    state.save(update_fields=list(fields) + ['updated_at'])
    return state


# ---------------------------------------------------------------------------
# 遗留哈希识别
# ---------------------------------------------------------------------------
def is_legacy_hash_encoded(encoded):
    """是否为历史 32 位小写 MD5（与 ``accounts.is_legacy_hash`` 同一判据）。"""
    return accounts.is_legacy_hash(encoded)


def sync_legacy_flag(account, account_type):
    """把账号当前是否持有遗留哈希同步到状态行。返回是否持有。"""
    pending = is_legacy_hash_encoded(getattr(account, 'password', '') or '')
    state = get_or_create_state(account_type, account.pk)
    if state is not None and state.legacy_hash_pending != pending:
        state.legacy_hash_pending = pending
        _save(state, ['legacy_hash_pending'])
    return pending


# ---------------------------------------------------------------------------
# 强制重置判定
# ---------------------------------------------------------------------------
def evaluate(account, account_type, now=None):
    """给出该账号在当前策略下的处置建议。

    返回 ``dict``：
        ``must_change``   bool —— 是否必须改密后才能继续使用
        ``reason``        str  —— ``legacy_hash`` / ``inactive`` / ``max_age`` / ''
        ``enabled``       bool —— 生命周期总开关
        ``active``        bool —— 账号是否启用（缺状态行时视为启用）
    """
    cfg = policy()
    now = now or timezone.now()
    state = get_state(account_type, account.pk)

    result = {
        'enabled': bool(cfg['ENABLED']),
        'must_change': False,
        'reason': '',
        'active': True if state is None else bool(state.is_active),
    }

    if state is None:
        # 表未落地：只按账号自身的哈希形态给建议，不阻断
        if is_legacy_hash_encoded(getattr(account, 'password', '') or ''):
            result['reason'] = 'legacy_hash'
        return result

    if state.must_change_password:
        result['must_change'] = True
        result['reason'] = result['reason'] or 'flagged'

    if not state.is_active:
        if cfg['FORCE_RESET_INACTIVE']:
            result['must_change'] = True
            result['reason'] = 'inactive'
        return result

    if cfg['FORCE_RESET_LEGACY'] and state.legacy_hash_pending:
        result['must_change'] = True
        result['reason'] = 'legacy_hash'

    max_age = int(cfg['MAX_AGE_DAYS'] or 0)
    if max_age > 0 and state.password_changed_at:
        age = (now - state.password_changed_at).days
        if age >= max_age:
            result['must_change'] = True
            result['reason'] = 'max_age'

    return result


# ---------------------------------------------------------------------------
# 会话世代（会话失效）
# ---------------------------------------------------------------------------
SESSION_EPOCH_KEY = 'sec_epoch'


def current_epoch(account_type, account_id):
    state = get_state(account_type, account_id)
    return 0 if state is None else int(state.session_epoch or 0)


def bump_epoch(account_type, account_id):
    """把会话世代 +1，使所有旧会话失效。"""
    state = get_or_create_state(account_type, account_id)
    if state is None:
        return None
    state.session_epoch = int(state.session_epoch or 0) + 1
    return _save(state, ['session_epoch'])


def write_session_epoch(session, account_type, account_id):
    """登录/改密成功后把当前世代写入会话。"""
    if session is None:
        return None
    epoch = current_epoch(account_type, account_id)
    session[SESSION_EPOCH_KEY] = epoch
    return epoch


def session_is_current(account_type, account_id, session):
    """会话是否仍然有效。

    判定顺序：
    1. 生命周期未启用 / 表未落地 → 一律视为有效（不改变既有行为）；
    2. 账号被停用 → 无效；
    3. 会话没有世代标记（旧会话）→ 无效（强制重新登录）；
    4. 世代不一致 → 无效。
    """
    if session is None or not lifecycle_enabled() or not table_available():
        return True
    state = get_state(account_type, account_id)
    if state is None:
        return True
    if not state.is_active:
        return False
    stored = session.get(SESSION_EPOCH_KEY)
    if stored is None:
        return False
    try:
        return int(stored) == int(state.session_epoch or 0)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 临时口令 / 改密
# ---------------------------------------------------------------------------
class PasswordLifecycleError(ValueError):
    """密码生命周期相关的业务拒绝。"""


def issue_temporary_password(account, account_type, actor=None, request=None, ttl_minutes=None):
    """管理员发起的一次性临时口令。

    - 明文只在返回值中出现一次，供管理员一次性转达，**不落库、不入日志**；
    - 状态行置 ``must_change_password`` 与到期时间；
    - 会话世代 +1，旧会话立即失效；
    - 写审计（不含明文）。
    """
    if account is None:
        raise PasswordLifecycleError('账号不存在')

    cfg = policy()
    ttl = int(ttl_minutes if ttl_minutes is not None else cfg['TEMP_PASSWORD_TTL_MINUTES'])
    raw = accounts.generate_password()

    accounts.set_password(account, raw)

    state = get_or_create_state(account_type, account.pk)
    if state is not None:
        state.must_change_password = True
        state.legacy_hash_pending = False
        state.temp_password_expires_at = timezone.now() + timezone.timedelta(minutes=ttl)
        state.session_epoch = int(state.session_epoch or 0) + 1
        state.last_reset_by = str(getattr(actor, 'pk', '') or '')[:32]
        _save(state, ['must_change_password', 'legacy_hash_pending',
                      'temp_password_expires_at', 'session_epoch', 'last_reset_by'])

    accounts.log_action(
        request, 'password_reset_temp', account,
        detail='temporary password issued ttl_minutes={}'.format(ttl))
    return raw, state


def change_password(account, account_type, raw_password, request=None,
                    enforce_policy=True, current_session=None):
    """用户自助改密（含首次强制改密）。

    成功后会清除强制改密标记、刷新 ``password_changed_at``、清除遗留哈希标记，
    并把会话世代 +1；若传入 ``current_session``，则为其写入新世代，
    避免用户改密后被自己的失效机制踢出。
    """
    if account is None:
        raise PasswordLifecycleError('账号不存在')
    if not raw_password:
        raise PasswordLifecycleError('密码不能为空')

    if enforce_policy:
        errors = accounts.password_errors(raw_password, account)
        if errors:
            raise PasswordLifecycleError('；'.join(errors))

    accounts.set_password(account, raw_password)

    state = get_or_create_state(account_type, account.pk)
    new_epoch = None
    if state is not None:
        state.must_change_password = False
        state.legacy_hash_pending = False
        state.password_changed_at = timezone.now()
        state.temp_password_expires_at = None
        state.session_epoch = int(state.session_epoch or 0) + 1
        new_epoch = state.session_epoch
        _save(state, ['must_change_password', 'legacy_hash_pending',
                      'password_changed_at', 'temp_password_expires_at', 'session_epoch'])

    if current_session is not None and new_epoch is not None:
        current_session[SESSION_EPOCH_KEY] = new_epoch

    accounts.log_action(request, 'password_change_lifecycle', account, detail='self service')
    return state


def deactivate(account, account_type, reason='', request=None):
    """停用账号并使其全部会话失效（不动账号表，只改状态表）。"""
    state = get_or_create_state(account_type, account.pk)
    if state is None:
        return None
    state.is_active = False
    state.session_epoch = int(state.session_epoch or 0) + 1
    _save(state, ['is_active', 'session_epoch'])
    accounts.log_action(request, 'account_deactivated', account, detail=(reason or '-')[:64])
    return state


def reactivate(account, account_type, request=None):
    state = get_or_create_state(account_type, account.pk)
    if state is None:
        return None
    state.is_active = True
    state.session_epoch = int(state.session_epoch or 0) + 1
    _save(state, ['is_active', 'session_epoch'])
    accounts.log_action(request, 'account_reactivated', account)
    return state


# ---------------------------------------------------------------------------
# 批量标记（不执行重置：重置需要单独授权）
# ---------------------------------------------------------------------------
ACCOUNT_MODELS = {
    'admin': ('app01.models', 'Admin'),
    'student': ('app01.models', 'Student'),
    'teacher': ('app01.models', 'Teacher'),
}


def _resolve_model(account_type):
    import importlib

    dotted, name = ACCOUNT_MODELS[account_type]
    return getattr(importlib.import_module(dotted), name)


def sweep(account_type, limit=500, dry_run=True):
    """扫描某类账号，登记遗留哈希与隐藏风险，供人工决定是否重置。

    **本函数不重置任何密码**——重置必须走 ``issue_temporary_password``
    或 ``change_password``，且真实用户重置需要单独授权。
    """
    if not table_available():
        return {'available': False, 'account_type': account_type, 'scanned': 0,
                'legacy': 0, 'created_states': 0, 'dry_run': dry_run}

    model = _resolve_model(account_type)
    model_cls = _model()

    scanned = legacy = created = 0
    qs = model.objects.all().only('id', 'password').order_by('pk')[:limit]
    for account in qs:
        scanned += 1
        pending = is_legacy_hash_encoded(account.password or '')
        if pending:
            legacy += 1
        if dry_run:
            continue
        _state, was_created = model_cls.objects.get_or_create(
            account_type=account_type,
            account_id=str(account.pk),
            defaults={'legacy_hash_pending': pending},
        )
        if was_created:
            created += 1
        elif _state.legacy_hash_pending != pending:
            _state.legacy_hash_pending = pending
            _state.save(update_fields=['legacy_hash_pending', 'updated_at'])

    cfg = policy()
    result = {
        'available': True,
        'account_type': account_type,
        'scanned': scanned,
        'legacy': legacy,
        'created_states': created,
        'dry_run': dry_run,
        'policy': {
            'forcing_legacy_reset': bool(cfg['FORCE_RESET_LEGACY']),
            'forcing_inactive_reset': bool(cfg['FORCE_RESET_INACTIVE']),
        },
    }
    logger.info(
        'password_sweep account_type=%s scanned=%s legacy=%s created=%s dry_run=%s',
        account_type, scanned, legacy, created, dry_run)
    return result
