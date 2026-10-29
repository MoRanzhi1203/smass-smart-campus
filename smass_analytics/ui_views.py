"""U6：R7 看板、报表与授权导出。

安全要点（全部有测试）：
- 计算一律走 `services.compute_metric`，**scope 先于聚合**；
- 被小样本抑制的指标，页面只显示"已抑制"，**数值不出现在 HTML/JSON/CSV**；
- 报表权限与指标权限双重校验。
"""
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from smass_analytics import services
from smass_analytics.models import (
    DataQualityIssue,
    MetricDefinition,
    ReportDefinition,
    ReportRun,
)
from smass_organization.views import roles_required

STAFF_ROLES = {'system_admin', 'college_admin', 'teacher'}


def _actor(request):
    account = getattr(request, 'user', None)
    return getattr(account, 'login_name', '') if account is not None else ''


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def dashboard_page(request):
    """看板：指标卡 + 数据源筛选 + 抑制标识。"""
    account = getattr(request, 'user', None)
    source_filter = (request.GET.get('source') or '').strip()

    metrics = services.enabled_metrics(account)
    if source_filter:
        metrics = [m for m in metrics if m.data_source == source_filter]

    rows = []
    for metric in metrics:
        try:
            value, meta = services.compute_metric(metric, account)
        except services.AnalyticsError:
            continue
        rows.append({
            # 同时提供 metric / code：旧 JSON 消费者用 metric，
            # 新模板用 code（向后兼容，不破坏既有测试）
            'metric': metric.code,
            'code': metric.code,
            'name': metric.name,
            'description': metric.description,
            'data_source': metric.data_source,
            'unit': metric.definition.get('unit', '') if isinstance(metric.definition, dict) else '',
            'version': metric.version,
            'value': meta['value'],
            'suppressed': meta['suppressed'],
            'query_hash': meta['query_hash'],
        })

    # AJAX / JSON 消费者（旧浏览器测试与新前端都用这条通道）
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'ok': True,
            'rows': rows,
            'source_filter': source_filter,
            'suppressed_count': sum(1 for r in rows if r['suppressed']),
        })

    return render(request, 'r7/dashboard.html', {
        'rows': rows,
        'sources': MetricDefinition.DATA_SOURCES,
        'source_filter': source_filter,
        'suppressed_count': sum(1 for r in rows if r['suppressed']),
    })


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def metric_list_page(request):
    """指标注册表 + 报表清单。"""
    account = getattr(request, 'user', None)

    metrics = MetricDefinition.objects.order_by('code')
    reports = ReportDefinition.objects.order_by('code')

    recent_runs = ReportRun.objects.select_related('report').order_by('-ran_at')[:10]
    issues = DataQualityIssue.objects.select_related('metric').order_by('-created_at')[:10]

    return render(request, 'r7/metric_list.html', {
        'metrics': metrics,
        'reports': reports,
        'recent_runs': recent_runs,
        'issues': issues,
        'enabled_count': metrics.filter(is_enabled=True).count(),
    })


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def report_detail_page(request, code):
    """运行单个报表并展示结果（含导出入口）。"""
    account = getattr(request, 'user', None)
    report = ReportDefinition.objects.filter(code=code).first()
    if report is None:
        return HttpResponse('报表不存在', status=404)

    roles = set(account.active_roles()) if account and account.is_active else set()
    if report.permission_roles and not (set(report.permission_roles) & roles):
        return HttpResponse('无权查看该报表', status=403)

    if not report.is_enabled:
        return render(request, 'r7/report_detail.html', {
            'report': report,
            'rows': [],
            'meta': {},
            'disabled': True,
        })

    rows, meta = services.run_report(report, account)

    return render(request, 'r7/report_detail.html', {
        'report': report,
        'rows': rows,
        'meta': meta,
        'disabled': False,
    })


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def report_export_page(request, code):
    """导出报表 CSV（与页面同一权限与同一 scope）。"""
    account = getattr(request, 'user', None)
    report = ReportDefinition.objects.filter(code=code).first()
    if report is None:
        return HttpResponse('报表不存在', status=404)

    roles = set(account.active_roles()) if account and account.is_active else set()
    if report.permission_roles and not (set(report.permission_roles) & roles):
        return HttpResponse('无权导出该报表', status=403)

    try:
        text, meta = services.export_report_csv(report, account)
    except services.AnalyticsError as exc:
        return HttpResponse(str(exc), status=403)

    response = HttpResponse(text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="{}.csv"'.format(report.code)
    response['X-Query-Hash'] = meta['query_hash']
    return response


@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def metric_series(request):
    """指标的最近快照序列（供图表；只返回已存快照，不重新计算）。"""
    code = (request.GET.get('code') or '').strip()
    metric = MetricDefinition.objects.filter(code=code).first()
    if metric is None:
        return JsonResponse({'ok': False, 'reason': '指标不存在'}, status=404)

    account = getattr(request, 'user', None)
    roles = set(account.active_roles()) if account and account.is_active else set()
    if metric.permission_roles and not (set(metric.permission_roles) & roles):
        return JsonResponse({'ok': False, 'reason': '无权查看'}, status=403)

    snapshots = metric.snapshots.order_by('-computed_at')[:20]
    points = [
        {'at': s.computed_at.strftime('%H:%M:%S'), 'value': float(s.value)}
        for s in reversed(list(snapshots))
    ]
    return JsonResponse({'ok': True, 'code': metric.code, 'points': points})
