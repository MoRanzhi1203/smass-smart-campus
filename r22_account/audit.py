"""G3 审计服务：Account 业务事件的唯一写入口。

三条硬规则：
1. **禁止**把 ``Account.pk`` 写进 ``django_admin_log.user_id``（L1）；
2. 成功审计与业务操作**同事务**提交（保证"有业务就有审计"）；
3. 失败/拒绝审计在业务事务**回滚之后**用独立写入记录，
   且明确标 ``outcome != success``，绝不误报成功。
"""
import re
import uuid
from contextlib import contextmanager

from django.db import transaction

from r22_account.models import (
    ACTOR_KIND_ACCOUNT,
    ACTOR_KIND_LEGACY,
    ACTOR_KIND_SYSTEM,
    ACTOR_KIND_UNKNOWN,
    OUTCOME_DENIED,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    AccountAuditEvent,
)

#: 敏感键（大小写不敏感）——命中即从 context 中移除
SENSITIVE_KEY_PATTERN = re.compile(
    r'(password|passwd|pwd|hash|token|secret|session|card_?id|id_?card|phone|otp)',
    re.IGNORECASE,
)

MAX_CONTEXT_CHARS = 2000


class AuditDisabled(Exception):
    """审计被显式关闭时抛出（用于测试开关语义）。"""


def new_request_id():
    return str(uuid.uuid4())


def sanitize(context):
    """剔除敏感键 + 截断，保证可安全落库与导出。"""
    if not context:
        return {}

    if not isinstance(context, dict):
        return {'value': str(context)[:200]}

    cleaned = {}
    for key, value in context.items():
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[str(key)[:64]] = value
        else:
            cleaned[str(key)[:64]] = str(value)[:200]

    # 粗略限长，避免超长 JSON
    total = 0
    trimmed = {}
    for key, value in cleaned.items():
        size = len(str(value))
        if total + size > MAX_CONTEXT_CHARS:
            break
        trimmed[key] = value
        total += size
    return trimmed


def _actor_fields(actor):
    """把 actor 统一成 (kind, login)。

    - ``Account`` → account
    - 规范化后的 legacy dict → legacy
    - ``None`` → unknown（**不**编造 auth.User）
    """
    if actor is None:
        return ACTOR_KIND_UNKNOWN, ''

    from r21_account.models import Account

    if isinstance(actor, Account):
        return ACTOR_KIND_ACCOUNT, actor.login_name

    if isinstance(actor, dict):
        return ACTOR_KIND_LEGACY, str(actor.get('id') or '')

    return ACTOR_KIND_SYSTEM, str(actor)[:32]


def record(action, outcome=OUTCOME_SUCCESS, *, actor=None, target='', target_id='',
           context=None, request=None, request_id='', actor_kind=None,
           batch_id='', operation='', source_batch_id='', counts=None):
    """写一条审计事件。返回事件对象。"""
    from r22_account import conf

    if not conf.flags()['audit_enabled']:
        raise AuditDisabled('审计已被 R22_FLAGS.audit_enabled 关闭')

    kind, login = _actor_fields(actor)
    if actor_kind is not None:
        kind = actor_kind

    ip = ''
    if request is not None:
        ip = (request.META.get('REMOTE_ADDR') or '')[:45]

    return AccountAuditEvent.objects.create(
        action=action[:48],
        outcome=outcome,
        actor_kind=kind,
        actor_login=login[:32],
        target=str(target)[:32],
        target_id=str(target_id)[:64],
        context=sanitize(context),
        ip=ip,
        request_id=(request_id or new_request_id())[:36],
        batch_id=(batch_id or '')[:36],
        operation=(operation or '')[:16],
        source_batch_id=(source_batch_id or '')[:36],
        counts=counts or {},
    )


def record_success(action, **kwargs):
    return record(action, OUTCOME_SUCCESS, **kwargs)


def record_denied(action, **kwargs):
    return record(action, OUTCOME_DENIED, **kwargs)


def record_error(action, **kwargs):
    return record(action, OUTCOME_ERROR, **kwargs)


@contextmanager
def business_with_audit(action, *, actor=None, target='', target_id='', context=None,
                        request=None):
    """上下文管理器：业务与"成功审计"同事务；失败则回滚并单独记录 error。

    用法：
        with business_with_audit('role_grant', actor=account, target='account', ...):
            do_business()
    """
    request_id = new_request_id()
    meta = dict(
        actor=actor, target=target, target_id=target_id,
        context=context, request=request, request_id=request_id,
    )

    try:
        with transaction.atomic():
            yield
            record_success(action, **meta)
    except Exception as exc:
        # 事务已回滚：这里必须用新的写入，否则审计会随业务一起丢失
        record_error(
            action,
            actor=actor,
            target=target,
            target_id=target_id,
            context=dict(context or {}, error=type(exc).__name__),
            request=request,
            request_id=request_id,
        )
        raise


def assert_no_admin_log_written(action_callable, *args, **kwargs):
    """测试辅助：执行动作后断言没有产生 ``django_admin_log`` 记录。"""
    from django.contrib.admin.models import LogEntry

    before = LogEntry.objects.count()
    result = action_callable(*args, **kwargs)
    after = LogEntry.objects.count()
    return result, before, after


def safe_record(action, **kwargs):
    """写审计并捕获失败（失败时发 security 告警，不静默）。"""
    try:
        return record(action, **kwargs)
    except Exception:  # noqa: BLE001
        from r22_account import alerts
        alerts.audit_failure(operation=kwargs.get('operation', action))
        raise
