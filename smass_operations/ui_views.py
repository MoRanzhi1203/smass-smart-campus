"""R10 UI/UX：新增页面视图（导入、API 文档、运维状态）。

对应 U3（导入）、U7（API 文档 / 运维状态）。全部复用既有服务层，
不新增业务规则。
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from smass_organization.views import roles_required

ADMIN_ROLES = {'system_admin', 'college_admin'}
STAFF_ROLES = {'system_admin', 'college_admin', 'teacher'}


# ---------------------------------------------------------------------------
# U3：数据导入
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*ADMIN_ROLES)
def import_page(request):
    """导入向导：上传 → 预览（零写入）→ 确认 → 结果。"""
    from smass_organization.models import DataImportJob, StudentRecord

    recent = DataImportJob.objects.order_by('-id')[:10]
    return render(request, 'r4/import.html', {
        'recent': recent,
        'student_count': StudentRecord.objects.count(),
    })


@require_POST
@roles_required(*ADMIN_ROLES)
def import_preview(request):
    """预览：只解析与校验，**不写任何数据**。"""
    from smass_organization import services

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'reason': '请求体不是合法 JSON'}, status=400)

    text = payload.get('csv') or ''
    if not text.strip():
        return JsonResponse({'ok': False, 'reason': '内容为空'}, status=400)

    account = getattr(request, 'user', None)
    try:
        result = services.import_preview(
            text, actor=getattr(account, 'login_name', '')
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'ok': False, 'reason': str(exc)[:200]}, status=400)

    if isinstance(result, dict):
        body = {'ok': True, 'preview': result}
    else:
        body = {'ok': True, 'preview': {'rows': result}}
    return JsonResponse(body)


# ---------------------------------------------------------------------------
# U7：API 文档
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def api_docs(request):
    """应用内 API 文档页：渲染既有 OpenAPI schema。"""
    from smass_api import services as api_services

    schema = api_services.openapi_schema()

    endpoints = []
    for path, methods in schema.get('paths', {}).items():
        for method, spec in methods.items():
            if method.startswith('x-'):
                continue
            endpoints.append({
                'method': method.upper(),
                'path': '/api/v1' + path,
                'summary': spec.get('summary', ''),
                'responses': sorted(spec.get('responses', {}).keys()),
            })
    endpoints.sort(key=lambda item: (item['path'], item['method']))

    return render(request, 'r8/docs.html', {
        'schema': schema,
        'schema_json': json.dumps(schema, ensure_ascii=False, indent=2),
        'endpoints': endpoints,
        'scope_list': list(api_services.ALL_SCOPES),
    })


# ---------------------------------------------------------------------------
# U7：运维状态
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*STAFF_ROLES)
def ops_status(request):
    """运维状态页：健康、就绪、遥测、告警（只读，无管理动作）。"""
    from smass_operations import services as ops_services
    from smass_operations.models import AlertEvent, AlertRule, ReadinessProbe

    ready_ok, checks = ops_services.readiness(persist=False)
    summary = ops_services.summary(300)
    triggered = ops_services.evaluate_rules(persist=False)

    return render(request, 'r9/status.html', {
        'ready_ok': ready_ok,
        'checks': checks,
        'summary': summary,
        'triggered': triggered,
        'triggered_codes': {item['rule'] for item in triggered},
        'rules': AlertRule.objects.order_by('code')[:20],
        'recent_events': AlertEvent.objects.select_related('rule').order_by('-created_at')[:10],
        'recent_probes': ReadinessProbe.objects.order_by('-checked_at')[:10],
    })
