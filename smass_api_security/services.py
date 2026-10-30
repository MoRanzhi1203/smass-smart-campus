"""S15 服务层：令牌、scope、限流、幂等、重放与审计。"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    CLIENT_ACTIVE,
    ApiClient,
    ApiRequestLog,
    ApiToken,
    IdempotencyKey,
    Nonce,
    RateLimitBucket,
)

logger = logging.getLogger('smass.audit')

ADMIN_ROLES = frozenset({RoleCode.SYSTEM_ADMIN})


class ApiError(Exception):
    def __init__(self, message, code='API_ERROR', status=400):
        self.code = code
        self.status = status
        super().__init__(message)


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)


def can_manage(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & ADMIN_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def hash_token(raw):
    return hashlib.sha256(str(raw or '').encode('utf-8')).hexdigest()


def create_client(actor, name):
    if not can_manage(actor):
        raise ApiError('只有管理员可以创建 API 客户端', code='PERMISSION_DENIED', status=403)
    if not str(name or '').strip():
        raise ApiError('名称不能为空', code='EMPTY_NAME', status=400)
    client = ApiClient.objects.create(
        name=str(name).strip()[:100],
        client_id='cli_' + uuid.uuid4().hex[:24],
        status=CLIENT_ACTIVE,
        created_by=_actor_id(actor))
    logger.info('api_client_created id=%s by=%s', client.pk, _actor_id(actor))
    return client


def issue_token(client, scopes, ttl_seconds=3600):
    if client.status != CLIENT_ACTIVE:
        raise ApiError('客户端已停用', code='CLIENT_DISABLED', status=403)
    raw = 'tok_' + secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        client=client,
        token_hash=hash_token(raw),
        scopes=','.join(str(item).strip() for item in (scopes or []) if str(item).strip())[:300],
        expires_at=timezone.now() + timezone.timedelta(seconds=max(1, ttl_seconds)))
    logger.info('api_token_issued client=%s by_ttl=%s', client.pk, ttl_seconds)
    return raw, token


def revoke_token(token, actor):
    if not can_manage(actor):
        raise ApiError('只有管理员可以吊销令牌', code='PERMISSION_DENIED', status=403)
    if token.revoked_at is not None:
        raise ApiError('令牌已吊销', code='BAD_STATE', status=400)
    token.revoked_at = timezone.now()
    token.save(update_fields=['revoked_at'])
    logger.info('api_token_revoked id=%s by=%s', token.pk, _actor_id(actor))
    return token


def _raw_token(request):
    header = request.META.get('HTTP_AUTHORIZATION', '') or ''
    if not header.lower().startswith('bearer '):
        return ''
    return header.split(' ', 1)[1].strip()


def authenticate(request):
    """返回 (token, ApiError)。"""
    raw = _raw_token(request)
    if not raw:
        return None, ApiError('缺少 Bearer 令牌', code='NO_TOKEN', status=401)
    token = ApiToken.objects.select_related('client').filter(
        token_hash=hash_token(raw)).first()
    if token is None:
        return None, ApiError('令牌无效', code='BAD_TOKEN', status=401)
    if token.revoked_at is not None:
        return None, ApiError('令牌已吊销', code='TOKEN_REVOKED', status=401)
    if token.expires_at <= timezone.now():
        return None, ApiError('令牌已过期', code='TOKEN_EXPIRED', status=401)
    if token.client.status != CLIENT_ACTIVE:
        return None, ApiError('客户端已停用', code='CLIENT_DISABLED', status=403)
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token, None


def has_scope(token, scope):
    if not scope:
        return True
    scopes = {item.strip() for item in (token.scopes or '').split(',') if item.strip()}
    return scope in scopes


def check_rate(token, limit, window_seconds=60):
    """固定窗口限流；返回 (allowed, remaining)。"""
    if limit <= 0:
        return True, None
    now = timezone.now()
    epoch = int(now.timestamp())
    window_start = timezone.datetime.fromtimestamp(
        epoch - (epoch % window_seconds), tz=now.tzinfo)
    with transaction.atomic():
        bucket, _created = RateLimitBucket.objects.get_or_create(
            token=token, window_start=window_start)
        RateLimitBucket.objects.filter(pk=bucket.pk).update(count=F('count') + 1)
        bucket.refresh_from_db()
    allowed = bucket.count <= limit
    return allowed, max(0, limit - bucket.count)


def check_replay(token, timestamp_raw, nonce):
    """时间戳窗口 + 一次性 nonce。"""
    if not timestamp_raw or not nonce:
        raise ApiError('缺少 X-Timestamp / X-Nonce', code='NO_REPLAY_HEADERS',
                       status=400)
    try:
        stamp = int(timestamp_raw)
    except (TypeError, ValueError):
        raise ApiError('X-Timestamp 非法', code='BAD_TIMESTAMP', status=400)
    now = int(timezone.now().timestamp())
    if abs(now - stamp) > 300:
        raise ApiError('请求时间戳超出允许窗口', code='STALE_TIMESTAMP', status=400)
    try:
        with transaction.atomic():  # savepoint：唯一冲突不污染外层事务
            Nonce.objects.create(token=token, nonce=str(nonce)[:64])
    except IntegrityError:
        raise ApiError('检测到重放请求', code='REPLAY_DETECTED', status=409)
    return True


def _digest(method, path, body):
    return hashlib.sha256(
        '{}|{}|{}'.format(method, path, body).encode('utf-8')).hexdigest()


def idempotency_lookup(token, key, digest):
    """返回 (hit, response_status, response_body)。"""
    row = IdempotencyKey.objects.filter(token=token, key=str(key)).first()
    if row is None:
        return False, None, None
    if row.request_digest != digest:
        raise ApiError('同一幂等键的请求体不一致', code='IDEMPOTENCY_CONFLICT',
                       status=409)
    return True, row.response_status, row.response_body


def store_idempotency(token, key, digest, status, body):
    try:
        with transaction.atomic():  # savepoint：并发同键不污染外层事务
            IdempotencyKey.objects.create(
                token=token, key=str(key)[:128], request_digest=digest,
                response_status=status, response_body=body)
    except IntegrityError:
        return False
    return True


def log_request(token, method, path, status, reason='', ip=''):
    prefix = token.token_hash[:8] if token is not None else ''
    ApiRequestLog.objects.create(
        token_hash_prefix=prefix, method=method[:8], path=path[:200],
        status=status, reason=str(reason or '')[:64], ip=str(ip or '')[:64])


def client_rows():
    return ApiClient.objects.select_related().order_by('-created_at')


def token_rows():
    return ApiToken.objects.select_related('client').order_by('-issued_at')


def scoped_logs(account):
    if not can_manage(account):
        return ApiRequestLog.objects.none()
    return ApiRequestLog.objects.order_by('-created_at')
