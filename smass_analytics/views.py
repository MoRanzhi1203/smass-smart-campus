"""R7 视图：指标看板、报表运行与导出。"""
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from smass_analytics import services
from smass_analytics.models import MetricDefinition, ReportDefinition
from smass_organization.views import roles_required

STAFF_ROLES = {'system_admin', 'college_admin', 'teacher'}


def health(request):
    return JsonResponse({
        'ok': True,
        'module': 'smass_analytics',
        'metrics': MetricDefinition.objects.count(),
        'enabled': MetricDefinition.objects.filter(is_enabled=True).count(),
        'reports': ReportDefinition.objects.count(),
    })


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def dashboard(request):
    account = getattr(request, 'user', None)
    metrics = services.enabled_metrics(account)

    rows = []
    for metric in metrics:
        try:
            value, meta = services.compute_metric(metric, account)
            rows.append(meta)
        except services.AnalyticsError:
            continue

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': rows})
    return render(request, 'r7/dashboard.html', {'rows': rows})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def metric_list(request):
    account = getattr(request, 'user', None)
    metrics = services.enabled_metrics(account)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': [
            {'code': m.code, 'name': m.name, 'version': m.version,
             'data_source': m.data_source, 'period': m.period}
            for m in metrics
        ]})
    return render(request, 'r7/metric_list.html', {'metrics': metrics})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def report_run(request, code):
    account = getattr(request, 'user', None)
    report = ReportDefinition.objects.filter(code=code).first()
    if report is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    try:
        rows, meta = services.run_report(report, account)
    except services.AnalyticsError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=403)

    return JsonResponse({'ok': True, 'rows': rows, 'meta': meta})


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def report_export(request, code):
    account = getattr(request, 'user', None)
    report = ReportDefinition.objects.filter(code=code).first()
    if report is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    try:
        text, meta = services.export_report_csv(report, account)
    except services.AnalyticsError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=403)

    response = HttpResponse(text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(report.code)
    response['X-Query-Hash'] = meta['query_hash']
    return response