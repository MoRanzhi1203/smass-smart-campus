"""S13 服务层：字段分级、最小化导出、受控披露与保留期清理。"""
from __future__ import annotations

import csv
import hashlib
import io
import logging

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode
from smass_organization.models import StudentRecord

from .models import (
    CLASSIFICATION_PERSONAL,
    CLASSIFICATION_PUBLIC,
    CLASSIFICATION_SENSITIVE,
    CLASSIFICATIONS,
    DISCLOSURE_APPROVED,
    DISCLOSURE_EXECUTED,
    DISCLOSURE_EXPIRED,
    DISCLOSURE_PENDING,
    DISCLOSURE_REJECTED,
    MASK_CHOICES,
    MASK_FULL,
    MASK_NONE,
    MASK_PARTIAL,
    DataField,
    DisclosureLog,
    DisclosureRequest,
    PrivacySample,
)

logger = logging.getLogger('smass.audit')

RESOURCE_STUDENT = 'student_record'
#: 需要强制脱敏的分级（即使配置为 none，导出也按 partial 处理）
SENSITIVE_CLASSES = {CLASSIFICATION_SENSITIVE, CLASSIFICATION_PERSONAL}
ADMIN_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})


class PrivacyError(ValueError):
    def __init__(self, message, code='PRIVACY_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(PrivacyError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def _is_self(account, identity):
    if account is None or identity is None:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def can_manage(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & ADMIN_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def set_field(actor, resource, field, classification, mask=MASK_NONE,
              retention_days=0, note=''):
    if not can_manage(actor):
        raise PermissionDenied('只有数据管理员可以配置字段分级')
    if not str(resource or '').strip() or not str(field or '').strip():
        raise PrivacyError('资源与字段不能为空', code='EMPTY_FIELD')
    if classification not in dict(CLASSIFICATIONS):
        raise PrivacyError('未知的分级', code='BAD_CLASSIFICATION')
    if mask not in dict(MASK_CHOICES):
        raise PrivacyError('未知的脱敏方式', code='BAD_MASK')

    policy, created = DataField.objects.update_or_create(
        resource=str(resource).strip(), field=str(field).strip(),
        defaults={'classification': classification, 'mask': mask,
                  'retention_days': int(retention_days or 0),
                  'note': str(note or '')[:200], 'enabled': True})
    logger.info('privacy_field_set resource=%s field=%s created=%s by=%s',
                policy.resource, policy.field, created, _actor_id(actor))
    return policy


def fields_of(resource, only_enabled=True):
    qs = DataField.objects.filter(resource=str(resource))
    if only_enabled:
        qs = qs.filter(enabled=True)
    return list(qs.order_by('field'))


def _mask(mask, value):
    if value is None:
        return None
    text = str(value)
    if mask == MASK_FULL:
        return '***'
    if mask == MASK_PARTIAL:
        if len(text) <= 6:
            return '*' * len(text)
        return '{}****{}'.format(text[:3], text[-2:])
    return text


def effective_mask(policy):
    if policy.classification in SENSITIVE_CLASSES and policy.mask == MASK_NONE:
        return MASK_PARTIAL
    return policy.mask


def _raw_value(record, field):
    if hasattr(record, field):
        return getattr(record, field)
    extra = getattr(record, 'extra', None)
    if isinstance(extra, dict):
        return extra.get(field)
    return None


def _records(resource):
    if resource == RESOURCE_STUDENT:
        return list(StudentRecord.objects.order_by('student_no'))
    return []


def minimized_rows(resource, fields, records=None):
    """按字段分级生成最小化后的行（只含已登记字段，敏感字段强制脱敏）。"""
    policies = {item.field: item for item in fields_of(resource)}
    wanted = [name for name in fields if name in policies]
    rows = []
    for record in (records if records is not None else _records(resource)):
        row = {}
        for name in wanted:
            policy = policies[name]
            row[name] = _mask(effective_mask(policy), _raw_value(record, name))
        rows.append(row)
    return wanted, rows


def request_disclosure(account, resource, fields, purpose):
    if getattr(account, 'pk', None) is None:
        raise PrivacyError('请先登录', code='NOT_AUTHENTICATED')
    if not str(purpose or '').strip():
        raise PrivacyError('必须填写披露用途', code='EMPTY_PURPOSE')
    requested = [str(item).strip() for item in (fields or []) if str(item).strip()]
    if not requested:
        raise PrivacyError('至少选择一个字段', code='EMPTY_FIELDS')

    available = {item.field for item in fields_of(resource)}
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise PrivacyError('字段未登记或未启用：{}'.format(','.join(unknown)),
                           code='UNKNOWN_FIELD')

    request = DisclosureRequest.objects.create(
        resource=str(resource), fields=requested,
        purpose=str(purpose).strip()[:500], requester=account,
        status=DISCLOSURE_PENDING)
    logger.info('disclosure_requested id=%s resource=%s fields=%s by=%s',
                request.pk, resource, ','.join(requested), _actor_id(account))
    return request


def approve_disclosure(request, actor):
    if not can_manage(actor):
        raise PermissionDenied('只有数据管理员可以批准披露')
    if request.status != DISCLOSURE_PENDING:
        raise PrivacyError('只有待审批申请可以批准', code='BAD_STATE')
    if _is_self(actor, request.requester_id):
        raise PrivacyError('不能审批自己提交的披露申请（双人原则）',
                           code='SELF_APPROVAL_DENIED')

    request.status = DISCLOSURE_APPROVED
    request.approver = actor
    request.approved_at = timezone.now()
    request.save(update_fields=['status', 'approver', 'approved_at'])
    logger.info('disclosure_approved id=%s by=%s', request.pk, _actor_id(actor))
    return request


def reject_disclosure(request, actor, reason):
    if not can_manage(actor):
        raise PermissionDenied('只有数据管理员可以驳回披露')
    if request.status != DISCLOSURE_PENDING:
        raise PrivacyError('只有待审批申请可以驳回', code='BAD_STATE')
    if _is_self(actor, request.requester_id):
        raise PrivacyError('不能驳回自己提交的披露申请（双人原则）',
                           code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise PrivacyError('驳回必须填写原因', code='EMPTY_REASON')

    request.status = DISCLOSURE_REJECTED
    request.approver = actor
    request.approved_at = timezone.now()
    request.reject_reason = str(reason).strip()[:255]
    request.save(update_fields=['status', 'approver', 'approved_at',
                                'reject_reason'])
    logger.info('disclosure_rejected id=%s by=%s', request.pk, _actor_id(actor))
    return request


def build_export(request):
    """生成 CSV 文本（确定性顺序），返回 (text, row_count, digest)。"""
    field_names, rows = minimized_rows(request.resource, list(request.fields or []))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    text = buffer.getvalue()
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return text, len(rows), digest


def execute_disclosure(request, actor):
    if request.status != DISCLOSURE_APPROVED:
        raise PrivacyError('只有已批准申请可以执行', code='BAD_STATE')
    if not (_is_self(actor, request.requester_id) or can_manage(actor)):
        raise PermissionDenied('只有申请人或数据管理员可以执行')

    text, row_count, digest = build_export(request)
    with transaction.atomic():
        locked = DisclosureRequest.objects.select_for_update().get(pk=request.pk)
        if locked.status != DISCLOSURE_APPROVED:
            raise PrivacyError('申请状态已变化', code='BAD_STATE')
        locked.status = DISCLOSURE_EXECUTED
        locked.executed_at = timezone.now()
        locked.executed_by = actor
        locked.row_count = row_count
        locked.output_digest = digest
        locked.save(update_fields=['status', 'executed_at', 'executed_by',
                                   'row_count', 'output_digest'])
        DisclosureLog.objects.create(
            request_id=locked.pk, resource=locked.resource,
            fields=list(locked.fields or []),
            actor_id_text=_actor_id(actor), row_count=row_count, digest=digest)
    logger.info('disclosure_executed id=%s rows=%s by=%s',
                request.pk, row_count, _actor_id(actor))
    return locked


def expire_stale(now=None, minutes=1440):
    now = now or timezone.now()
    threshold = now - timezone.timedelta(minutes=max(1, minutes))
    return DisclosureRequest.objects.filter(
        status=DISCLOSURE_PENDING, created_at__lt=threshold,
    ).update(status=DISCLOSURE_EXPIRED)


def purge_expired(now=None):
    """按字段 ``retention_days`` 清理过期样本。"""
    now = now or timezone.now()
    deleted = 0
    resources = set(PrivacySample.objects.values_list('resource', flat=True))
    for resource in resources:
        retention = [item.retention_days for item in fields_of(resource)
                     if item.retention_days > 0]
        if not retention:
            continue
        days = min(retention)
        threshold = now - timezone.timedelta(days=days)
        count, _detail = PrivacySample.objects.filter(
            resource=resource, created_at__lt=threshold).delete()
        deleted += count
    if deleted:
        logger.info('privacy_samples_purged count=%s', deleted)
    return deleted


def scoped_requests(account):
    qs = DisclosureRequest.objects.select_related('requester', 'approver')
    if can_manage(account):
        return qs.order_by('status', '-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(requester=account).order_by('-created_at')


def scoped_logs(account):
    if not can_manage(account):
        return DisclosureLog.objects.none()
    return DisclosureLog.objects.order_by('-created_at')


def stats():
    return {
        'fields': DataField.objects.filter(enabled=True).count(),
        'requests': DisclosureRequest.objects.count(),
        'executed': DisclosureRequest.objects.filter(
            status=DISCLOSURE_EXECUTED).count(),
        'samples': PrivacySample.objects.count(),
    }
