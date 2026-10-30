"""S09 服务层：TOTP、恢复码、启用/验证与特权判定。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_PENDING,
    MfaDevice,
    RecoveryCode,
)

logger = logging.getLogger('smass.audit')

STEP_SECONDS = 30
DIGITS = 6
DEFAULT_WINDOW = 1
RECOVERY_CODE_COUNT = 8

#: 特权角色（可通过 settings.MFA_REQUIRED_ROLES 覆盖）
PRIVILEGED_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})

SESSION_FLAG = 'mfa_verified_at'
SESSION_TTL_SECONDS = 12 * 60 * 60


class MfaError(ValueError):
    def __init__(self, message, code='MFA_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(MfaError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def mfa_enabled():
    return bool(getattr(settings, 'MFA_ENABLED', True))


def required_roles():
    configured = getattr(settings, 'MFA_REQUIRED_ROLES', None)
    if configured:
        return frozenset(configured)
    return PRIVILEGED_ROLES


def is_privileged(account):
    roles = set(authz.active_roles(account))
    return bool(roles & required_roles())


# ---------------------------------------------------------------------------
# TOTP（RFC 6238）
# ---------------------------------------------------------------------------
def generate_secret():
    return base64.b32encode(os.urandom(20)).decode('ascii').rstrip('=')


def _normalize_secret(secret):
    raw = str(secret or '').strip().replace(' ', '').upper()
    padding = '=' * ((8 - len(raw) % 8) % 8)
    return base64.b32decode(raw + padding, casefold=True)


def totp(secret, at=None, step=STEP_SECONDS, digits=DIGITS):
    """返回给定时间片的 TOTP 码。"""
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(_normalize_secret(secret),
                      struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def verify_totp(secret, code, at=None, window=DEFAULT_WINDOW):
    text = str(code or '').strip()
    if not text.isdigit() or len(text) != DIGITS:
        return False
    now = at if at is not None else time.time()
    for delta in range(-window, window + 1):
        if hmac.compare_digest(totp(secret, at=now + delta * STEP_SECONDS), text):
            return True
    return False


def provisioning_uri(account, secret):
    label = quote('SMASS:{}'.format(getattr(account, 'login_name', account.pk)))
    return 'otpauth://totp/{}?secret={}&issuer=SMASS&digits={}&period={}'.format(
        label, secret, DIGITS, STEP_SECONDS)


# ---------------------------------------------------------------------------
# 恢复码
# ---------------------------------------------------------------------------
def _hash_code(code):
    return hashlib.sha256(str(code).encode('utf-8')).hexdigest()


def _issue_recovery_codes(account):
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(os.urandom(5)).decode('ascii').rstrip('=')
        raw = raw[:8]
        RecoveryCode.objects.create(account=account, code_hash=_hash_code(raw))
        codes.append(raw)
    return codes


def _consume_recovery_code(account, code):
    digest = _hash_code(str(code or '').strip().upper())
    updated = RecoveryCode.objects.filter(
        account=account, code_hash=digest, used_at__isnull=True,
    ).update(used_at=timezone.now())
    return bool(updated)


# ---------------------------------------------------------------------------
# 启用 / 验证
# ---------------------------------------------------------------------------
def enroll(account):
    """生成/重置待确认设备，返回 (device, provisioning_uri)。"""
    if getattr(account, 'pk', None) is None:
        raise MfaError('请先登录', code='NOT_AUTHENTICATED')
    device = MfaDevice.objects.filter(account=account).first()
    secret = generate_secret()
    if device is None:
        device = MfaDevice.objects.create(
            account=account, secret=secret, status=STATUS_PENDING)
    else:
        if device.status == STATUS_ACTIVE:
            raise MfaError('MFA 已启用，请先停用后再重新绑定', code='ALREADY_ACTIVE')
        device.secret = secret
        device.status = STATUS_PENDING
        device.failed_attempts = 0
        device.confirmed_at = None
        device.save(update_fields=['secret', 'status', 'failed_attempts',
                                   'confirmed_at'])
    logger.info('mfa_enrolled account=%s', _actor_id(account))
    return device, provisioning_uri(account, secret)


def confirm(account, code):
    """校验 TOTP 并启用，返回一次性恢复码列表。"""
    device = MfaDevice.objects.filter(account=account).first()
    if device is None:
        raise MfaError('请先开始绑定 MFA', code='NO_DEVICE')
    if device.status == STATUS_ACTIVE:
        raise MfaError('MFA 已启用', code='ALREADY_ACTIVE')
    if not verify_totp(device.secret, code):
        device.failed_attempts += 1
        device.save(update_fields=['failed_attempts'])
        raise MfaError('验证码不正确', code='BAD_CODE')

    device.status = STATUS_ACTIVE
    device.failed_attempts = 0
    device.confirmed_at = timezone.now()
    device.save(update_fields=['status', 'failed_attempts', 'confirmed_at'])

    # 作废旧恢复码后重新签发（queryset.delete 绕过 append-only 保护，属受控操作）
    RecoveryCode.objects.filter(account=account, used_at__isnull=True).delete()
    codes = _issue_recovery_codes(account)
    logger.info('mfa_confirmed account=%s', _actor_id(account))
    return codes


def verify(account, code, at=None):
    """二次验证：TOTP 或恢复码。成功后写 session 标记。"""
    device = MfaDevice.objects.filter(
        account=account, status=STATUS_ACTIVE).first()
    if device is None:
        raise MfaError('MFA 未启用', code='NOT_ENROLLED')

    if verify_totp(device.secret, code, at=at):
        device.last_used_at = timezone.now()
        device.failed_attempts = 0
        device.save(update_fields=['last_used_at', 'failed_attempts'])
        logger.info('mfa_verified account=%s method=totp', _actor_id(account))
        return 'totp'

    if _consume_recovery_code(account, code):
        device.last_used_at = timezone.now()
        device.save(update_fields=['last_used_at'])
        logger.info('mfa_verified account=%s method=recovery', _actor_id(account))
        return 'recovery'

    device.failed_attempts += 1
    device.save(update_fields=['failed_attempts'])
    raise MfaError('验证码不正确', code='BAD_CODE')


def mark_session_verified(session):
    session[SESSION_FLAG] = timezone.now().isoformat()


def session_verified(session):
    raw = session.get(SESSION_FLAG)
    if not raw:
        return False
    try:
        from django.utils.dateparse import parse_datetime
        stamp = parse_datetime(raw)
    except (TypeError, ValueError):
        return False
    if stamp is None:
        return False
    if timezone.is_naive(stamp):
        stamp = timezone.make_aware(stamp)
    return (timezone.now() - stamp).total_seconds() <= SESSION_TTL_SECONDS


def clear_session_verified(session):
    session.pop(SESSION_FLAG, None)


def disable(account, code):
    """停用 MFA：必须提供有效验证码，防止会话被劫持后直接关闭。"""
    device = MfaDevice.objects.filter(
        account=account, status=STATUS_ACTIVE).first()
    if device is None:
        raise MfaError('MFA 未启用', code='NOT_ENROLLED')
    if not (verify_totp(device.secret, code) or _consume_recovery_code(account, code)):
        raise MfaError('验证码不正确', code='BAD_CODE')
    device.status = STATUS_DISABLED
    device.save(update_fields=['status'])
    logger.info('mfa_disabled account=%s', _actor_id(account))
    return device


def device_status(account):
    device = MfaDevice.objects.filter(account=account).first()
    if device is None:
        return {'exists': False, 'status': None, 'active': False}
    return {'exists': True, 'status': device.status,
            'active': device.status == STATUS_ACTIVE,
            'last_used_at': device.last_used_at,
            'recovery_remaining': RecoveryCode.objects.filter(
                account=account, used_at__isnull=True).count()}


def regenerate_recovery_codes(account, code):
    device = MfaDevice.objects.filter(
        account=account, status=STATUS_ACTIVE).first()
    if device is None:
        raise MfaError('MFA 未启用', code='NOT_ENROLLED')
    if not verify_totp(device.secret, code):
        raise MfaError('验证码不正确', code='BAD_CODE')
    RecoveryCode.objects.filter(account=account, used_at__isnull=True).delete()
    return _issue_recovery_codes(account)


def needs_setup(account):
    """特权角色且未启用 MFA。"""
    if not mfa_enabled() or not is_privileged(account):
        return False
    device = MfaDevice.objects.filter(account=account).first()
    return device is None or device.status != STATUS_ACTIVE
