"""R2.2 探针视图（隔离配置专用，正式 URL 不挂载）。"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from r22_account import audit


def _identity_payload(identity):
    account = identity.account
    return {
        'kind': identity.kind,
        'reason': identity.reason,
        'has_account': account is not None,
        'account_login': getattr(account, 'login_name', None),
        'account_active': getattr(account, 'is_active', None),
        'legacy_role': identity.legacy_role,
        'legacy_id': identity.legacy_id,
    }


def identity_view(request):
    """返回当前请求的身份解析结果（不含敏感信息）。

    刻意同时访问 ``r22_identity()``、``account``、``legacy_identity`` 三个入口，
    用于验证"每请求只解析一次"的缓存语义。
    """
    identity = request.r22_identity()
    # 同时访问两个懒入口，验证"每请求只解析一次"；真正取类型用解包后的 identity.account
    _lazy_account = request.account
    _lazy_legacy = request.legacy_identity

    account = identity.account

    payload = _identity_payload(identity)
    payload['account_type'] = type(account).__name__ if account else None
    payload['legacy_present'] = bool(_lazy_legacy)
    payload['legacy'] = bool(identity.legacy)
    return JsonResponse({'ok': True, 'identity': payload})


@require_http_methods(['POST'])
def audit_probe_view(request):
    """触发一次审计（用于验证 G3 的路由与脱敏）。"""
    try:
        event = audit.record_success(
            'probe_action',
            actor=request.account,
            target='probe',
            target_id='1',
            context={'note': 'probe', 'password': 'must-be-removed'},
            request=request,
        )
    except audit.AuditDisabled as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=409)

    return JsonResponse({
        'ok': True,
        'event_id': event.pk,
        'outcome': event.outcome,
        'actor_kind': event.actor_kind,
        'context': event.context,
    })


@require_http_methods(['POST'])
def audit_fail_probe_view(request):
    """业务失败 → 业务回滚，但 error 审计必须留下。"""
    from django.db import transaction

    from r22_account.models import AccountAuditEvent

    try:
        with audit.business_with_audit(
            'probe_failing_business',
            actor=request.account,
            target='probe',
            target_id='2',
            context={'note': 'will fail'},
            request=request,
        ):
            raise RuntimeError('simulated business failure')
    except RuntimeError:
        pass

    return JsonResponse({
        'ok': True,
        'events': list(
            AccountAuditEvent.objects.filter(action='probe_failing_business')
            .values('outcome', 'actor_kind')
        ),
    })


def legacy_parity_view(request):
    """最小 legacy 路由（验证 compat 模式下旧路径仍可达）。"""
    info = request.session.get('info') or {}
    return JsonResponse({
        'ok': True,
        'route': 'legacy_parity',
        'legacy_role': info.get('type'),
        'legacy_id': info.get('id'),
    })
