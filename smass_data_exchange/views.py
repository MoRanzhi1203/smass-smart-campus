"""S25 数据交换中心的 HTTP 层。

可见业务流程（主任务书 S25 强制要求）：

    模板下载 → 选择文件 → 校验/预览 → 确认提交 → 进度/结果 → 错误下载 → 导入历史

权限：所有端点都要求已登录，并且**每个数据集**的预览/提交都要通过
``r21_account.authorization`` 的 ``import`` 动作（默认拒绝）。
"""
from __future__ import annotations

import json
from functools import wraps
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .adapters import all_adapters
from .export import export_dataset
from .parsing import ParseError
from .schema import MAX_UPLOAD_BYTES, get
from .service import (
    TicketError,
    build_error_workbook,
    commit,
    load_job_errors,
    preview,
)
from .templates import build_template

def _login_url():
    """取当前 settings 的登录页（R4 是 /r4/login/，R5 是 /r5/login/）。"""
    from django.conf import settings

    return getattr(settings, 'LOGIN_URL', '/r4/login/')


def require_login(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_authenticated', False):
            target = request.get_full_path()
            return redirect('{}?next={}'.format(_login_url(), quote(target)))
        return view(request, *args, **kwargs)

    return _wrapped


def _schema_or_404(dataset):
    try:
        return get(dataset)
    except Exception:
        return None


def _wants_json(request):
    return (request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', ''))


def _read_upload(request):
    upload = request.FILES.get('file')
    if upload is None:
        raise ParseError('未选择文件', code='NO_FILE')
    if upload.size > MAX_UPLOAD_BYTES:
        raise ParseError(
            '文件过大（{} 字节），上限 {} 字节'.format(upload.size, MAX_UPLOAD_BYTES),
            code='TOO_LARGE')
    return upload.read(), upload.name


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@require_GET
@require_login
def exchange_home(request):
    """数据集列表：每个数据集提供 xlsx / csv 模板下载与导入入口。"""
    datasets = []
    for adapter in all_adapters():
        schema = adapter.schema
        datasets.append({
            'code': schema.code,
            'title': schema.title,
            'version': schema.version,
            'field_count': len(schema.fields),
            'required': schema.required_codes,
        })
    return render(request, 'exchange/index.html', {'datasets': datasets})


@require_GET
@require_login
def import_page(request, dataset):
    schema = _schema_or_404(dataset)
    if schema is None:
        return HttpResponse('未知数据集', status=404)
    return render(request, 'exchange/import.html', {
        'dataset': schema.code,
        'schema': schema,
        'fields': schema.fields,
        'required_codes': schema.required_codes,
        'instructions': schema.instructions,
        'notes': schema.notes,
        'max_upload_mb': round(MAX_UPLOAD_BYTES / 1024 / 1024, 1),
    })


# ---------------------------------------------------------------------------
# 模板下载
# ---------------------------------------------------------------------------
@require_GET
@require_login
def template_download(request, dataset):
    schema = _schema_or_404(dataset)
    if schema is None:
        return HttpResponse('未知数据集', status=404)
    fmt = (request.GET.get('fmt') or 'xlsx').lower()
    try:
        content, filename, mime = build_template(schema, fmt)
    except ValueError as exc:
        return HttpResponse(str(exc), status=400)

    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
    response['X-Template-Version'] = schema.version
    return response


# ---------------------------------------------------------------------------
# 预检 / 提交
# ---------------------------------------------------------------------------
@require_POST
@require_login
def api_preview(request, dataset):
    schema = _schema_or_404(dataset)
    if schema is None:
        return JsonResponse({'ok': False, 'error': '未知数据集'}, status=404)

    try:
        content, filename = _read_upload(request)
    except ParseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code},
                            status=400)

    result = preview(content, filename, dataset, request.user, request=request)
    return JsonResponse(result)


@require_POST
@require_login
def api_commit(request, dataset):
    schema = _schema_or_404(dataset)
    if schema is None:
        return JsonResponse({'ok': False, 'error': '未知数据集'}, status=404)

    token = (request.POST.get('ticket') or '').strip()
    if not token:
        return JsonResponse({'ok': False, 'error': '缺少预检令牌，请先预检'},
                            status=400)

    try:
        content, filename = _read_upload(request)
    except ParseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code},
                            status=400)

    try:
        result = commit(token, content, filename, dataset, request.user,
                        request=request,
                        allow_partial=request.POST.get('allow_partial') == '1')
    except TicketError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code},
                            status=409)
    except ParseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code},
                            status=400)

    return JsonResponse(result)


# ---------------------------------------------------------------------------
# 错误工作簿 / 历史 / 导出
# ---------------------------------------------------------------------------
@require_GET
@require_login
def error_download(request, dataset, job_id):
    schema = _schema_or_404(dataset)
    if schema is None:
        return HttpResponse('未知数据集', status=404)

    job, errors = load_job_errors(job_id)
    if job is None:
        return HttpResponse('导入作业不存在', status=404)
    if not errors:
        return HttpResponse('该作业没有错误记录', status=404)

    content = build_error_workbook(errors, dataset)
    response = HttpResponse(
        content,
        content_type=('application/vnd.openxmlformats-officedocument'
                      '.spreadsheetml.sheet'))
    response['Content-Disposition'] = 'attachment; filename="smass_errors_{}.xlsx"'.format(
        int(job_id))
    return response


@require_GET
@require_login
def job_history(request, dataset):
    schema = _schema_or_404(dataset)
    if schema is None:
        return HttpResponse('未知数据集', status=404)

    try:
        from smass_organization.models import DataImportJob
    except Exception:  # noqa: BLE001
        jobs = []
    else:
        jobs = list(
            DataImportJob.objects.filter(kind=schema.code[:32])
            .order_by('-created_at')[:50]
            .values('pk', 'status', 'total_rows', 'success_rows', 'error_rows',
                    'created_by', 'created_at', 'committed_at')
        )

    if _wants_json(request):
        return JsonResponse({'ok': True, 'jobs': [
            {**j, 'created_at': j['created_at'].isoformat() if j['created_at'] else None,
             'committed_at': (j['committed_at'].isoformat()
                              if j['committed_at'] else None)}
            for j in jobs
        ]})

    return render(request, 'exchange/history.html', {
        'dataset': schema.code,
        'schema': schema,
        'jobs': jobs,
    })


@require_GET
@require_login
def export_view(request, dataset):
    """按授权域导出（实际数据由调用方提供；此处以当前数据集字段为准）。"""
    schema = _schema_or_404(dataset)
    if schema is None:
        return HttpResponse('未知数据集', status=404)

    from r21_account import authorization as authz

    if not authz.has_action(request.user, 'export'):
        return HttpResponse('无导出权限', status=403)

    # 导出数据来自业务适配器（此处仅演示字段级裁剪与公式注入中和的接线）
    fmt = (request.GET.get('fmt') or 'csv').lower()
    allowed = authz.visible_fields(request.user, 'student')
    allowed_codes = None if allowed == authz.ALL_FIELDS else [
        c for c in schema.codes if c in allowed]

    rows = _export_rows(dataset, request.user, allowed_codes)
    content, filename, mime = export_dataset(
        dataset, rows, fmt=fmt, allowed_codes=allowed_codes)

    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
    return response


def _export_rows(dataset, account, allowed_codes):
    """从业务模块取导出行（当前仅 R4 学生档案）。"""
    if dataset != 'r4_students':
        return []
    try:
        from smass_organization import services as org_services
    except Exception:  # noqa: BLE001
        return []

    qs = org_services.scoped_students(account).select_related('unit')[:5000]
    return [{
        'student_no': s.student_no,
        'name': s.name,
        'unit_code': getattr(s.unit, 'code', '') if s.unit_id else '',
        'status': s.status,
        'enrolled_at': s.enrolled_at.isoformat() if s.enrolled_at else '',
    } for s in qs]
