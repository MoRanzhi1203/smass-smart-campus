"""S15 端点装饰器：统一认证、scope、限流、幂等、重放与审计。"""
from __future__ import annotations

import json
from functools import wraps

from django.http import HttpResponse, JsonResponse

from . import services


def _json_error(error):
    return JsonResponse({'status': False, 'error': error.code,
                         'message': str(error)},
                        status=error.status)


def api_endpoint(scope=None, limit=10, window=60, idempotent=False):
    """包装一个 API 视图。

    视图签名 ``view(request, token)``，返回 ``(dict, status)`` 或 ``dict``。
    """

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            ip = request.META.get('REMOTE_ADDR', '')
            token, error = services.authenticate(request)
            if error is not None:
                services.log_request(token, request.method, request.path,
                                     error.status, error.code, ip)
                return _json_error(error)

            if not services.has_scope(token, scope):
                services.log_request(token, request.method, request.path, 403,
                                     'SCOPE_DENIED', ip)
                return _json_error(services.ApiError(
                    '缺少 scope：{}'.format(scope), code='SCOPE_DENIED', status=403))

            try:
                services.check_replay(
                    token, request.META.get('HTTP_X_TIMESTAMP'),
                    request.META.get('HTTP_X_NONCE'))
            except services.ApiError as exc:
                services.log_request(token, request.method, request.path,
                                     exc.status, exc.code, ip)
                return _json_error(exc)

            allowed, remaining = services.check_rate(token, limit, window)
            if not allowed:
                services.log_request(token, request.method, request.path, 429,
                                     'RATE_LIMITED', ip)
                response = _json_error(services.ApiError(
                    '请求过于频繁', code='RATE_LIMITED', status=429))
                response['X-RateLimit-Remaining'] = '0'
                return response

            body = request.body.decode('utf-8', 'replace') if request.body else ''
            digest = services._digest(request.method, request.path, body)

            idem_key = request.META.get('HTTP_IDEMPOTENCY_KEY', '')
            if idempotent:
                if not idem_key:
                    services.log_request(token, request.method, request.path,
                                         400, 'MISSING_IDEMPOTENCY_KEY', ip)
                    return _json_error(services.ApiError(
                        '该端点要求 Idempotency-Key', code='MISSING_IDEMPOTENCY_KEY',
                        status=400))
                try:
                    hit, cached_status, cached_body = services.idempotency_lookup(
                        token, idem_key, digest)
                except services.ApiError as exc:
                    services.log_request(token, request.method, request.path,
                                         exc.status, exc.code, ip)
                    return _json_error(exc)
                if hit:
                    services.log_request(token, request.method, request.path,
                                         cached_status, 'IDEMPOTENT_REPLAY', ip)
                    response = JsonResponse(
                        json.loads(cached_body or '{}'),
                        status=cached_status, safe=False)
                    response['Idempotent-Replayed'] = 'true'
                    return response

            result = view(request, token, *args, **kwargs)
            if isinstance(result, HttpResponse):
                # 例如 @require_http_methods 直接返回 405
                services.log_request(token, request.method, request.path,
                                     result.status_code, 'HTTP_METHOD', ip)
                return result
            if isinstance(result, tuple):
                payload, status = result
            else:
                payload, status = result, 200

            if idempotent and idem_key:
                services.store_idempotency(
                    token, idem_key, digest, status,
                    json.dumps(payload, ensure_ascii=False))

            services.log_request(token, request.method, request.path, status,
                                 'OK', ip)
            response = JsonResponse(payload, status=status, safe=False)
            if remaining is not None:
                response['X-RateLimit-Remaining'] = str(remaining)
            return response

        return _wrapped

    return decorator
