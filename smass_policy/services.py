"""S11 服务层：字段策略判定、脱敏与决策审计。"""
from __future__ import annotations

import logging

from django.db import transaction

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    MASK_FULL,
    MASK_NONE,
    MASK_PARTIAL,
    FieldPolicy,
    PolicyDecisionLog,
)

logger = logging.getLogger('smass.audit')

ADMIN_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})


class PolicyError(ValueError):
    def __init__(self, message, code='POLICY_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(PolicyError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def roles_of(account):
    return set(authz.active_roles(account))


def can_admin(account):
    roles = roles_of(account)
    if not roles:
        return False
    if roles & ADMIN_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def _tokens(raw):
    return {part.strip() for part in str(raw or '').split(',') if part.strip()}


def _policy(resource, field):
    return FieldPolicy.objects.filter(
        resource=str(resource), field=str(field), enabled=True).first()


def _condition_value(obj, key):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def condition_ok(policy, obj):
    condition = policy.condition or {}
    if not condition:
        return True
    for key, allowed in condition.items():
        actual = _condition_value(obj, key)
        if actual is None:
            return False
        if isinstance(allowed, (list, tuple, set)):
            if str(actual) not in {str(item) for item in allowed}:
                return False
        elif str(actual) != str(allowed):
            return False
    return True


def _decide(account, resource, field, *, write=False, obj=None):
    """返回 (allowed, policy, reason)。"""
    policy = _policy(resource, field)
    if policy is None:
        return False, None, 'NO_POLICY'
    roles = roles_of(account)
    if not roles:
        return False, policy, 'NO_ROLE'
    allowed_roles = _tokens(policy.write_roles if write else policy.read_roles)
    if not (roles & allowed_roles):
        return False, policy, 'ROLE_DENIED'
    if not condition_ok(policy, obj):
        return False, policy, 'CONDITION_DENIED'
    return True, policy, 'OK'


def _log(account, resource, field, action, allowed, masked, reason):
    PolicyDecisionLog.objects.create(
        account_id_text=_actor_id(account), resource=str(resource)[:64],
        field=str(field)[:64], action=action, allowed=allowed,
        masked=masked, reason=reason[:64])


def mask_value(policy, value):
    if value is None:
        return None
    text = str(value)
    if policy.mask == MASK_FULL:
        return '***'
    if policy.mask == MASK_PARTIAL:
        if len(text) <= 6:
            return '*' * len(text)
        return '{}****{}'.format(text[:3], text[-2:])
    return text


def _raw_value(obj, field):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(field)
    if hasattr(obj, field):
        return getattr(obj, field)
    extra = getattr(obj, 'extra', None)
    if isinstance(extra, dict):
        return extra.get(field)
    return None


def read_field(account, resource, field, obj=None, *, log=True):
    """返回 {'allowed', 'value', 'masked', 'reason'}。"""
    allowed, policy, reason = _decide(account, resource, field, obj=obj)
    if not allowed:
        if log:
            _log(account, resource, field, 'read', False, False, reason)
        return {'allowed': False, 'value': None, 'masked': False,
                'reason': reason}
    value = _raw_value(obj, field)
    masked_value = mask_value(policy, value)
    masked = masked_value != value and value is not None
    if log:
        _log(account, resource, field, 'read', True, masked, 'OK')
    return {'allowed': True, 'value': masked_value, 'masked': masked,
            'reason': 'OK'}


def can_write(account, resource, field, obj=None, *, log=True):
    allowed, _policy_row, reason = _decide(
        account, resource, field, write=True, obj=obj)
    if log:
        _log(account, resource, field, 'write', allowed, False, reason)
    return allowed


def effective_fields(account, resource, obj=None, *, log=False):
    """该账号对该资源所有已配置字段的读写能力。"""
    result = {}
    for policy in FieldPolicy.objects.filter(resource=str(resource)):
        if not policy.enabled:
            continue
        read_allowed, _p, _r = _decide(account, resource, policy.field, obj=obj)
        write_allowed = can_write(account, resource, policy.field, obj=obj,
                                  log=False)
        result[policy.field] = {
            'read': read_allowed,
            'write': write_allowed,
            'mask': policy.mask,
        }
    return result


def set_policy(account, resource, field, *, read_roles='', write_roles='',
               mask=MASK_NONE, condition=None, note='', enabled=True):
    if not can_admin(account):
        raise PermissionDenied('只有管理员可以配置字段策略')
    if not str(resource or '').strip() or not str(field or '').strip():
        raise PolicyError('资源与字段不能为空', code='EMPTY_FIELD')
    if mask not in (MASK_NONE, MASK_PARTIAL, MASK_FULL):
        raise PolicyError('未知的脱敏方式', code='BAD_MASK')

    with transaction.atomic():
        policy, created = FieldPolicy.objects.update_or_create(
            resource=str(resource).strip(), field=str(field).strip(),
            defaults={
                'read_roles': str(read_roles or '')[:200],
                'write_roles': str(write_roles or '')[:200],
                'mask': mask,
                'condition': condition or {},
                'note': str(note or '')[:200],
                'enabled': bool(enabled),
            })
    logger.info('policy_set resource=%s field=%s created=%s by=%s',
                policy.resource, policy.field, created, _actor_id(account))
    return policy


def disable_policy(account, policy):
    if not can_admin(account):
        raise PermissionDenied('只有管理员可以配置字段策略')
    if not policy.enabled:
        raise PolicyError('策略已停用', code='BAD_STATE')
    policy.enabled = False
    policy.save(update_fields=['enabled', 'updated_at'])
    logger.info('policy_disabled id=%s by=%s', policy.pk, _actor_id(account))
    return policy


def scoped_policies(account):
    if can_admin(account):
        return FieldPolicy.objects.order_by('resource', 'field')
    return FieldPolicy.objects.none()


def decision_logs(account):
    if not can_admin(account):
        return PolicyDecisionLog.objects.none()
    return PolicyDecisionLog.objects.order_by('-created_at')


def all_resources():
    return sorted(FieldPolicy.objects.values_list('resource', flat=True).distinct())
