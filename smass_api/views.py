"""R8 视图：/api/v1/ 版本化资源、OpenAPI、mock 同步。"""
import json
import time

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from smass_api import services


def _error(code, message, status):
    return JsonResponse({'error': {'code': code, 'message': message}}, status=status)


def _int(value, default, minimum=1, maximum=100):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _guard(request, scope):
    """认证 + scope + 限流；返回 (account, None) 或 (None, error_response)。"""
    account = services.authenticate(request)
    if account is None:
        return None, _error('UNAUTHENTICATED', '缺少有效的服务令牌', 401)
    try:
        services.require_scope(account, scope)
        services.check_rate_limit(account)
    except services.ApiError as exc:
        return account, _error(exc.code, exc.message, exc.status)
    return account, None


def _respond(request, account, handler):
    started = time.perf_counter()
    try:
        body = handler()
        response = JsonResponse(body)
        status = 200
    except services.ApiError as exc:
        response = _error(exc.code, exc.message, exc.status)
        status = exc.status
    services.log_call(account, request, status, (time.perf_counter() - started) * 1000)
    return response


@require_http_methods(['GET'])
def units(request):
    account, failure = _guard(request, services.SCOPE_READ_UNITS)
    if failure:
        return failure
    return _respond(request, account, lambda: services.list_units(
        account,
        page=_int(request.GET.get('page'), 1, 1, 10 ** 6),
        page_size=_int(request.GET.get('page_size'), 20),
        keyword=request.GET.get('q'),
    ))


@require_http_methods(['GET'])
def students(request):
    account, failure = _guard(request, services.SCOPE_READ_STUDENTS)
    if failure:
        return failure
    return _respond(request, account, lambda: services.list_students(
        account,
        page=_int(request.GET.get('page'), 1, 1, 10 ** 6),
        page_size=_int(request.GET.get('page_size'), 20),
        unit_code=request.GET.get('unit'),
        keyword=request.GET.get('q'),
    ))


@require_http_methods(['GET'])
def sections(request):
    account, failure = _guard(request, services.SCOPE_READ_SECTIONS)
    if failure:
        return failure
    return _respond(request, account, lambda: services.list_sections(
        account,
        page=_int(request.GET.get('page'), 1, 1, 10 ** 6),
        page_size=_int(request.GET.get('page_size'), 20),
    ))


@require_http_methods(['GET'])
def instances(request):
    account, failure = _guard(request, services.SCOPE_READ_WORKFLOW)
    if failure:
        return failure
    return _respond(request, account, lambda: services.list_workflow_instances(
        account,
        page=_int(request.GET.get('page'), 1, 1, 10 ** 6),
        page_size=_int(request.GET.get('page_size'), 20),
        status=request.GET.get('status'),
    ))


@csrf_exempt
@require_http_methods(['POST'])
def sync(request):
    account, failure = _guard(request, services.SCOPE_WRITE_STUDENTS)
    if failure:
        return failure

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return _error('INVALID_JSON', '请求体不是合法 JSON', 400)

    key = request.headers.get('Idempotency-Key', '')

    try:
        cached, fingerprint = services.begin_idempotent(account, key, payload)
    except services.ApiError as exc:
        return _error(exc.code, exc.message, exc.status)

    if cached is not None:
        response = JsonResponse(cached['body'], status=cached['status'])
        response['Idempotent-Replayed'] = 'true'
        return response

    started = time.perf_counter()
    try:
        result = services.run_mock_sync(account, payload)
        body = {'ok': True, 'result': result}
        status = 200
    except services.ApiError as exc:
        body = {'error': {'code': exc.code, 'message': exc.message}}
        status = exc.status

    services.store_idempotent(key, account, fingerprint, status, body)
    services.log_call(account, request, status, (time.perf_counter() - started) * 1000)
    return JsonResponse(body, status=status)


@require_http_methods(['GET'])
def openapi(request):
    return JsonResponse(services.openapi_schema())