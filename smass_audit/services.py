"""S16 服务层：哈希链审计、链校验与安全告警。"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

from django.db.models import Count
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    ALERT_ACK,
    ALERT_DENIED_BURST,
    ALERT_OPEN,
    RESULT_DENIED,
    RESULT_SUCCESS,
    RESULTS,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    AuditEvent,
    SecurityAlert,
)

logger = logging.getLogger('smass.audit')

AUDIT_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})

#: 告警窗口与阈值（可在设置中覆盖）
DEFAULT_WINDOW_MINUTES = 10
DEFAULT_THRESHOLD = 5


class AuditError(ValueError):
    def __init__(self, message, code='AUDIT_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(AuditError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def can_audit(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & AUDIT_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def _require_audit(account):
    if not can_audit(account):
        raise PermissionDenied('只有审计管理员可以执行该操作')


def _payload(event_no, actor_id, actor_role, action, resource, resource_id,
             result, reason, ip, meta):
    body = {
        'event_no': event_no,
        'actor_id': str(actor_id or ''),
        'actor_role': str(actor_role or ''),
        'action': str(action or ''),
        'resource': str(resource or ''),
        'resource_id': str(resource_id or ''),
        'result': str(result or ''),
        'reason': str(reason or ''),
        'ip': str(ip or ''),
        'meta': meta or {},
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _hash(prev_hash, payload):
    return hashlib.sha256('{}{}'.format(prev_hash or '', payload).encode('utf-8')).hexdigest()


def record(actor, action, *, resource='', resource_id='', result=RESULT_SUCCESS,
           reason='', ip='', meta=None, actor_role=''):
    """写入一条审计事件（哈希链）。"""
    if result not in dict(RESULTS):
        raise AuditError('未知的审计结果', code='BAD_RESULT')
    if not str(action or '').strip():
        raise AuditError('审计动作不能为空', code='EMPTY_ACTION')

    last = AuditEvent.objects.order_by('-id').first()
    prev_hash = last.hash if last is not None else ''
    event_no = 'EVT-{}'.format(uuid.uuid4().hex[:20])
    payload = _payload(event_no, _actor_id(actor), actor_role, action, resource,
                       resource_id, result, reason, ip, meta)
    event = AuditEvent.objects.create(
        event_no=event_no,
        actor_id=_actor_id(actor),
        actor_role=str(actor_role or '')[:32],
        action=str(action).strip()[:64],
        resource=str(resource or '')[:64],
        resource_id=str(resource_id or '')[:64],
        result=result,
        reason=str(reason or '')[:120],
        ip=str(ip or '')[:64],
        meta=meta or {},
        prev_hash=prev_hash,
        hash=_hash(prev_hash, payload),
    )
    logger.info('audit_event action=%s result=%s actor=%s resource=%s',
                event.action, event.result, event.actor_id, event.resource)
    return event


def verify_chain(limit=None):
    """校验哈希链完整性，返回 {'ok', 'count', 'broken_at'}。"""
    qs = AuditEvent.objects.order_by('id')
    if limit:
        qs = qs[:limit]
    prev_hash = ''
    count = 0
    for event in qs:
        payload = _payload(event.event_no, event.actor_id, event.actor_role,
                           event.action, event.resource, event.resource_id,
                           event.result, event.reason, event.ip, event.meta)
        expected = _hash(prev_hash, payload)
        if event.prev_hash != prev_hash or event.hash != expected:
            return {'ok': False, 'count': count, 'broken_at': event.pk}
        prev_hash = event.hash
        count += 1
    return {'ok': True, 'count': count, 'broken_at': None}


def detect_alerts(window_minutes=DEFAULT_WINDOW_MINUTES,
                  threshold=DEFAULT_THRESHOLD):
    """窗口内 denied 次数超阈值 → 生成告警（同主体窗口内只开一条）。"""
    since = timezone.now() - timezone.timedelta(minutes=max(1, window_minutes))
    rows = (AuditEvent.objects
            .filter(result=RESULT_DENIED, created_at__gte=since)
            .values('actor_id')
            .annotate(total=Count('id')))
    created = 0
    for row in rows:
        actor = row['actor_id'] or '(anonymous)'
        total = row['total']
        if total < threshold:
            continue
        exists = SecurityAlert.objects.filter(
            alert_type=ALERT_DENIED_BURST, subject=actor, status=ALERT_OPEN,
            created_at__gte=since).exists()
        if exists:
            continue
        SecurityAlert.objects.create(
            alert_type=ALERT_DENIED_BURST,
            severity=SEVERITY_HIGH if total >= threshold * 2 else SEVERITY_MEDIUM,
            subject=actor,
            detail={'count': total, 'window_minutes': window_minutes,
                    'threshold': threshold,
                    'since': since.isoformat()},
            status=ALERT_OPEN)
        created += 1
    if created:
        logger.warning('audit_alerts_created count=%s window=%s',
                       created, window_minutes)
    return created


def acknowledge_alert(alert, actor):
    _require_audit(actor)
    if alert.status != ALERT_OPEN:
        raise AuditError('告警已确认', code='BAD_STATE')
    alert.status = ALERT_ACK
    alert.acknowledged_by = _actor_id(actor)
    alert.acknowledged_at = timezone.now()
    alert.save(update_fields=['status', 'acknowledged_by', 'acknowledged_at'])
    logger.info('audit_alert_acknowledged id=%s by=%s',
                alert.pk, _actor_id(actor))
    return alert


def scoped_events(account):
    qs = AuditEvent.objects.all()
    if can_audit(account):
        return qs.order_by('-id')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(actor_id=_actor_id(account)).order_by('-id')


def scoped_alerts(account):
    if not can_audit(account):
        return SecurityAlert.objects.none()
    return SecurityAlert.objects.order_by('status', '-created_at')


def stats(account=None):
    if account is not None and not can_audit(account):
        qs = AuditEvent.objects.filter(actor_id=_actor_id(account))
    else:
        qs = AuditEvent.objects.all()
    return {
        'events': qs.count(),
        'denied': qs.filter(result=RESULT_DENIED).count(),
        'open_alerts': SecurityAlert.objects.filter(status=ALERT_OPEN).count(),
        'chain': verify_chain(),
    }
