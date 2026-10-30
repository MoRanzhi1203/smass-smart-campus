"""S10 服务层：再认证证明、双人审批与执行日志。"""
from __future__ import annotations

import hashlib
import json
import logging

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    APPROVAL_APPROVED,
    APPROVAL_EXECUTED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    METHOD_PASSWORD,
    METHOD_TOTP,
    SENSITIVE_ACTIONS,
    DualApproval,
    OperationLog,
    StepUpProof,
)

logger = logging.getLogger('smass.audit')

APPROVER_ROLES = frozenset({RoleCode.SYSTEM_ADMIN})
DEFAULT_TTL = 300
DEFAULT_EXPIRE_MINUTES = 60


class StepUpError(ValueError):
    def __init__(self, message, code='STEPUP_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(StepUpError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def _is_self(account, identity):
    if account is None or identity is None:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def action_spec(code):
    spec = SENSITIVE_ACTIONS.get(str(code or ''))
    if spec is None:
        raise StepUpError('未知的敏感操作', code='UNKNOWN_ACTION')
    return spec


def can_approve(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & APPROVER_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def _digest(payload):
    return hashlib.sha256(json.dumps(
        payload or {}, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# 再认证
# ---------------------------------------------------------------------------
def verify_stepup(account, action_code, code, *, method=METHOD_PASSWORD, ip=''):
    """再认证成功则写入证明并返回。"""
    spec = action_spec(action_code)
    if getattr(account, 'pk', None) is None:
        raise StepUpError('请先登录', code='NOT_AUTHENTICATED')
    if method not in (METHOD_PASSWORD, METHOD_TOTP):
        raise StepUpError('未知的再认证方式', code='BAD_METHOD')

    if method == METHOD_TOTP:
        from smass_mfa import services as mfa_services
        try:
            mfa_services.verify(account, code)
        except mfa_services.MfaError as exc:
            raise StepUpError('TOTP 验证失败：{}'.format(exc), code='BAD_CODE')
    else:
        if not account.check_password(str(code or '')):
            raise StepUpError('密码不正确', code='BAD_CODE')

    ttl = int(spec.get('ttl', DEFAULT_TTL))
    proof = StepUpProof.objects.create(
        account=account, action_code=str(action_code),
        method=method, ip=str(ip or '')[:64],
        expires_at=timezone.now() + timezone.timedelta(seconds=max(1, ttl)))
    logger.info('stepup_verified account=%s action=%s method=%s',
                _actor_id(account), action_code, method)
    return proof


def has_stepup(account, action_code):
    if getattr(account, 'pk', None) is None:
        return False
    return StepUpProof.objects.filter(
        account=account, action_code=str(action_code),
        expires_at__gt=timezone.now()).exists()


# ---------------------------------------------------------------------------
# 双人审批
# ---------------------------------------------------------------------------
def open_approval(account, action_code, payload, reason):
    spec = action_spec(action_code)
    if not has_stepup(account, action_code):
        raise StepUpError('请先完成再认证', code='STEPUP_REQUIRED')
    if not str(reason or '').strip():
        raise StepUpError('必须填写申请事由', code='EMPTY_REASON')
    if not isinstance(payload, dict):
        raise StepUpError('操作载荷必须是对象', code='BAD_PAYLOAD')

    approval = DualApproval.objects.create(
        action_code=str(action_code),
        payload=payload,
        payload_digest=_digest(payload),
        reason=str(reason).strip()[:500],
        requester=account,
        status=APPROVAL_PENDING,
    )
    logger.info('stepup_approval_opened id=%s action=%s by=%s',
                approval.pk, action_code, _actor_id(account))
    return approval


def expire_stale(now=None, minutes=DEFAULT_EXPIRE_MINUTES):
    now = now or timezone.now()
    threshold = now - timezone.timedelta(minutes=max(1, minutes))
    return DualApproval.objects.filter(
        status=APPROVAL_PENDING, created_at__lt=threshold,
    ).update(status=APPROVAL_EXPIRED)


def approve_approval(approval, actor):
    if not can_approve(actor):
        raise PermissionDenied('只有审批人角色可以批准')
    if approval.status != APPROVAL_PENDING:
        raise StepUpError('只有待审批工单可以批准', code='BAD_STATE')
    if _is_self(actor, approval.requester_id):
        raise StepUpError('不能审批自己发起的工单（双人审批）',
                          code='SELF_APPROVAL_DENIED')
    if _digest(approval.payload) != approval.payload_digest:
        raise StepUpError('工单载荷已被篡改，拒绝批准', code='PAYLOAD_TAMPERED')

    approval.status = APPROVAL_APPROVED
    approval.approver = actor
    approval.approved_at = timezone.now()
    approval.save(update_fields=['status', 'approver', 'approved_at'])
    logger.info('stepup_approval_approved id=%s by=%s',
                approval.pk, _actor_id(actor))
    return approval


def reject_approval(approval, actor, reason):
    if not can_approve(actor):
        raise PermissionDenied('只有审批人角色可以驳回')
    if approval.status != APPROVAL_PENDING:
        raise StepUpError('只有待审批工单可以驳回', code='BAD_STATE')
    if _is_self(actor, approval.requester_id):
        raise StepUpError('不能驳回自己发起的工单（双人审批）',
                          code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise StepUpError('驳回必须填写原因', code='EMPTY_REASON')

    approval.status = APPROVAL_REJECTED
    approval.approver = actor
    approval.approved_at = timezone.now()
    approval.reject_reason = str(reason).strip()[:255]
    approval.save(update_fields=['status', 'approver', 'approved_at',
                                 'reject_reason'])
    logger.info('stepup_approval_rejected id=%s by=%s',
                approval.pk, _actor_id(actor))
    return approval


def execute_approval(approval, actor):
    """执行敏感操作：只有已批准、且执行人是发起人或审批人。"""
    if approval.status != APPROVAL_APPROVED:
        raise StepUpError('只有已批准工单可以执行', code='BAD_STATE')
    if not (_is_self(actor, approval.requester_id) or can_approve(actor)):
        raise PermissionDenied('只有发起人或审批人可以执行')
    if _digest(approval.payload) != approval.payload_digest:
        raise StepUpError('工单载荷已被篡改，拒绝执行', code='PAYLOAD_TAMPERED')

    with transaction.atomic():
        locked = DualApproval.objects.select_for_update().get(pk=approval.pk)
        if locked.status != APPROVAL_APPROVED:
            raise StepUpError('工单状态已变化', code='BAD_STATE')
        locked.status = APPROVAL_EXECUTED
        locked.executed_at = timezone.now()
        locked.executed_by = actor
        locked.save(update_fields=['status', 'executed_at', 'executed_by'])
        OperationLog.objects.create(
            action_code=locked.action_code,
            payload_digest=locked.payload_digest,
            actor=actor,
            actor_id_text=_actor_id(actor),
            approval_id=locked.pk,
            result='executed',
            detail='双人审批执行：{}'.format(locked.reason)[:200],
        )

    logger.info('stepup_approval_executed id=%s by=%s action=%s',
                approval.pk, _actor_id(actor), approval.action_code)
    return locked


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def scoped_approvals(account):
    qs = DualApproval.objects.select_related('requester', 'approver')
    if can_approve(account):
        return qs.order_by('status', '-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(requester=account).order_by('-created_at')


def scoped_operation_logs(account):
    if not can_approve(account):
        return OperationLog.objects.none()
    return OperationLog.objects.order_by('-created_at')


def action_catalog():
    return [{'code': code, 'label': spec['label'],
             'dual': spec.get('dual', True), 'ttl': spec.get('ttl', DEFAULT_TTL)}
            for code, spec in SENSITIVE_ACTIONS.items()]
