"""S17：会话空闲超时与设备活动刷新中间件。

默认关闭（``SESSION_SECURITY['ENABLED']=False``），启用后：

- 超过 ``IDLE_TIMEOUT_MINUTES`` 无活动 → 清空会话并跳转登录（带 ``next``）；
- 未超时 → 按 ``TOUCH_INTERVAL_SECONDS`` 节流刷新 ``last_activity``
  与设备 ``last_seen``，避免每个请求都写 session 表与设备表。

中间件顺序（见 ``smass/settings.py``）：``SessionMiddleware`` → ... →
``PasswordLifecycleMiddleware`` → ``SessionSecurityMiddleware``。
即"会话存在性 → 强制改密 → 空闲超时"，超时判定永远建立在已登录会话之上。
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect

from app01.services import session_security

logger = logging.getLogger('smass.audit')


class SessionSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, 'session', None) and request.session.get('info'):
            if session_security.check_idle_timeout(request):
                logger.info(
                    'session_idle_timeout role=%s ip=%s',
                    (request.session.get('info') or {}).get('type', '-'),
                    request.META.get('REMOTE_ADDR', '-'),
                )
                request.session.flush()
                login_url = getattr(settings, 'LOGIN_URL', '/login/')
                return redirect('{}?next={}'.format(
                    login_url, quote(request.get_full_path())))
            try:
                session_security.touch_session(request)
            except Exception:  # noqa: BLE001 - 设备表不可用不应阻断请求
                logger.warning('session_device_touch_failed')
        return self.get_response(request)
