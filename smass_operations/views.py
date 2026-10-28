"""R9 视图：liveness / readiness / 指标 / 告警。"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from smass_operations import services


@require_http_methods(['GET'])
def health(request):
    """liveness：进程活着即 200，不查数据库。"""
    return JsonResponse({'ok': True, 'status': 'alive'})


@require_http_methods(['GET'])
def ready(request):
    """readiness：数据库连 + 迁移无 pending。"""
    ok, checks = services.readiness()
    return JsonResponse({'ok': ok, 'checks': checks},
                        status=200 if ok else 503)


@require_http_methods(['GET'])
def metrics(request):
    window = request.GET.get('window')
    try:
        window_seconds = int(window) if window else 300
    except ValueError:
        window_seconds = 300
    return JsonResponse({'ok': True, 'summary': services.summary(window_seconds)})


@require_http_methods(['GET'])
def alerts(request):
    triggered = services.evaluate_rules(persist=False)
    return JsonResponse({'ok': True, 'triggered': triggered})
# ---------------------------------------------------------------------------
# R10-01 统一导航
# ---------------------------------------------------------------------------
def nav_home(request):
    """统一入口：展示导航与当前角色，未登录也可访问（便于排障）。"""
    from django.shortcuts import render

    account = getattr(request, 'user', None)
    roles = []
    if account is not None and getattr(account, 'is_authenticated', False):
        try:
            roles = sorted(account.active_roles())
        except Exception:  # noqa: BLE001
            roles = []

    return render(request, 'r10/home.html', {
        'account': account if roles else None,
        'roles': roles,
    })
