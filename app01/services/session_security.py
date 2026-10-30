"""S17：登录设备、会话踢出与空闲超时。

设计原则
--------
- 设备标识写入服务端 session，不信任客户端提交的 device_id；
- 踢出设备 = 删除对应 Django Session 行 + 标记设备已撤销；
- 空闲超时默认关闭（``SESSION_SECURITY['ENABLED']``），避免影响既有部署；
- 只记录 IP 与 UA 的截断值，不记录密码/令牌等敏感内容。
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone

from app01.models import LoginDevice

MAX_USER_AGENT = 200

#: session 内活动时间戳的刷新间隔（秒）。避免每个请求都写 session / 写设备表。
TOUCH_INTERVAL_SECONDS = 60


def _config():
    return getattr(settings, 'SESSION_SECURITY', {}) or {}


def idle_timeout_minutes():
    try:
        return int(_config().get('IDLE_TIMEOUT_MINUTES', 30))
    except (TypeError, ValueError):
        return 30


def enabled():
    return bool(_config().get('ENABLED'))


def register_device(request, account, role=''):
    """登录成功后登记设备，并初始化空闲计时。"""
    device_id = request.session.get('device_id') or uuid.uuid4().hex
    request.session['device_id'] = device_id
    _now = timezone.now()
    request.session['last_activity'] = _now.isoformat()
    request.session['device_touch_at'] = _now.isoformat()

    if not request.session.session_key:
        request.session.save()

    LoginDevice.objects.update_or_create(
        device_id=device_id,
        defaults={
            'user_id': str(getattr(account, 'pk', '')),
            'role': (role or '')[:16],
            'session_key': request.session.session_key or '',
            'ip': (request.META.get('REMOTE_ADDR', '') or '')[:64],
            'user_agent': (request.META.get('HTTP_USER_AGENT', '') or '')[:MAX_USER_AGENT],
            'revoked_at': None,
        },
    )
    return device_id


def touch_device(request):
    """刷新最近活动时间与会话键（会话可能被轮换）。"""
    device_id = request.session.get('device_id')
    if not device_id:
        return
    LoginDevice.objects.filter(device_id=device_id, revoked_at__isnull=True).update(
        last_seen=timezone.now(),
        session_key=request.session.session_key or '',
    )


def _seconds_since(raw):
    """把 ISO 时间戳转换成"距今秒数"；非法值返回 None。"""
    if not raw:
        return None
    try:
        ts = timezone.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(ts):
        ts = timezone.make_aware(ts)
    return (timezone.now() - ts).total_seconds()


def touch_session(request, interval=TOUCH_INTERVAL_SECONDS):
    """节流刷新会话活动时间与设备 last_seen。

    空闲超时判定精度为 ``interval`` 秒，对本场景（默认 30 分钟）足够，
    同时避免每个请求都写 session 表与设备表。
    """
    elapsed = _seconds_since(request.session.get('device_touch_at'))
    if elapsed is not None and elapsed < interval:
        return False
    now = timezone.now()
    if enabled():
        request.session['last_activity'] = now.isoformat()
    request.session['device_touch_at'] = now.isoformat()
    touch_device(request)
    return True


def list_devices(user_id, role=None):
    qs = LoginDevice.objects.filter(
        user_id=str(user_id), revoked_at__isnull=True)
    if role:
        qs = qs.filter(role=role)
    return qs.order_by('-last_seen')


def revoke_device(user_id, device_id, role=None):
    """踢出指定设备：删除服务端会话并标记撤销。

    必须同时匹配 ``user_id``（并可选匹配 ``role``），否则同一字符串 ID 在
    不同角色模型间会互相越权踢出（IDOR）。
    """
    qs = LoginDevice.objects.filter(
        user_id=str(user_id), device_id=device_id, revoked_at__isnull=True)
    if role:
        qs = qs.filter(role=role)
    device = qs.first()
    if device is None:
        return False
    if device.session_key:
        Session.objects.filter(session_key=device.session_key).delete()
    device.revoked_at = timezone.now()
    device.save(update_fields=['revoked_at'])
    return True


def revoke_other_devices(user_id, keep_device_id, role=None):
    """踢出除当前设备外的所有会话。"""
    revoked = 0
    for device in list_devices(user_id, role=role).exclude(device_id=keep_device_id):
        if revoke_device(user_id, device.device_id, role=role):
            revoked += 1
    return revoked


def check_idle_timeout(request):
    """返回 True 表示已超时（调用方应让会话失效）。"""
    if not enabled():
        return False
    elapsed = _seconds_since(request.session.get('last_activity'))
    if elapsed is None:
        return False
    return elapsed > idle_timeout_minutes() * 60
