"""R4 视图：组织树、学生档案、导入预检（隔离模块）。

权限：服务端默认拒绝；组织 scope 与字段级权限在**服务层**落实，
视图只负责把"已过滤"的数据交给模板。
"""
import json
from functools import wraps

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from smass_organization import services
from smass_organization.models import (
    OrganizationUnit,
    StudentRecord,
    StudentRecordChange,
)

ADMIN_ROLES = {'system_admin'}
COLLEGE_ROLES = {'system_admin', 'college_admin'}
TEACHER_ROLES = {'system_admin', 'college_admin', 'teacher'}


def _roles(request):
    user = getattr(request, 'user', None)
    return services.account_roles(user)


def roles_required(*allowed):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            roles = _roles(request)
            if not roles & set(allowed):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'ok': False, 'reason': 'forbidden'}, status=403)
                return HttpResponse('无权限', status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def health(request):
    return JsonResponse({
        'ok': True,
        'module': 'smass_organization',
        'units': OrganizationUnit.objects.count(),
        'students': StudentRecord.objects.count(),
    })


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def unit_tree(request):
    """返回组织树（JSON）。"""
    units = list(
        services.scoped_units(getattr(request, 'user', None))
        .values('id', 'code', 'name', 'unit_type', 'parent_id', 'status')
    )
    return JsonResponse({'ok': True, 'units': units})


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def unit_list(request):
    units = services.scoped_units(getattr(request, 'user', None)).order_by('sort_order', 'code')
    return render(request, 'r4/unit_list.html', {'units': units})


@require_POST
@roles_required(*ADMIN_ROLES)
def unit_create(request):
    data = json.loads(request.body or '{}')
    try:
        unit = services.create_unit(
            code=data.get('code', '').strip(),
            name=data.get('name', '').strip(),
            unit_type=data.get('unit_type', ''),
            parent=OrganizationUnit.objects.filter(pk=data.get('parent')).first(),
            sort_order=int(data.get('sort_order', 0)),
        )
    except services.OrganizationError as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)

    return JsonResponse({'ok': True, 'id': unit.pk, 'code': unit.code})


@require_POST
@roles_required(*ADMIN_ROLES)
def unit_move(request, pk):
    data = json.loads(request.body or '{}')
    unit = OrganizationUnit.objects.filter(pk=pk).first()
    if unit is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    new_parent = OrganizationUnit.objects.filter(pk=data.get('parent')).first()
    try:
        services.move_unit(unit, new_parent,
                           actor=getattr(request.user, 'login_name', ''))
    except services.CycleError as exc:
        return JsonResponse({'ok': False, 'code': 'CYCLE', 'reason': str(exc)}, status=400)
    except services.InvalidHierarchyError as exc:
        return JsonResponse({'ok': False, 'code': 'INVALID_HIERARCHY',
                             'reason': str(exc)}, status=400)

    return JsonResponse({'ok': True})


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def student_list(request):
    """学生列表：字段级过滤（无权限字段不出现在上下文里）。"""
    account = getattr(request, 'user', None)
    record = services.scoped_students(account).select_related('unit').order_by('student_no')

    unit_code = request.GET.get('unit')
    if unit_code:
        record = record.filter(unit__code=unit_code)

    keyword = request.GET.get('q')
    if keyword:
        record = record.filter(name__icontains=keyword)

    fields = [f.code for f in services.visible_fields(account)]
    rows = [
        {
            'student_no': item.student_no,
            'name': item.name,
            'unit': item.unit.code if item.unit else '',
            'status': item.status,
            'extra': services.filtered_extra(item, account),
        }
        for item in record[:200]
    ]

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'rows': rows, 'visible_fields': fields})

    return render(request, 'r4/student_list.html', {
        'rows': rows, 'visible_fields': fields,
    })


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def student_detail(request, student_no):
    account = getattr(request, 'user', None)
    record = StudentRecord.objects.filter(student_no=student_no).select_related('unit').first()
    if record is None:
        return JsonResponse({'ok': False, 'reason': 'not found'}, status=404)

    # R4-01：对象级 scope 校验（防 IDOR）
    if not services.can_access_student(account, record):
        return JsonResponse({'ok': False, 'reason': 'forbidden'}, status=403)

    history = list(
        StudentRecordChange.objects.filter(record=record)
        .order_by('-changed_at')
        .values('field_name', 'old_value', 'new_value', 'changed_by', 'changed_at')[:50]
    )

    payload = {
        'student_no': record.student_no,
        'name': record.name,
        'unit': record.unit.code if record.unit else '',
        'status': record.status,
        'version': record.version,
        'extra': services.filtered_extra(record, account),
        'history': history,
    }
    return JsonResponse({'ok': True, 'student': payload})


@csrf_exempt
@require_POST
@roles_required(*ADMIN_ROLES)
def import_preview_view(request):
    text = request.body.decode('utf-8', 'replace')
    job, preview = services.import_preview(
        text, actor=getattr(request.user, 'login_name', '')
    )
    return JsonResponse({
        'ok': job.status != 'failed',
        'batch_id': str(job.batch_id),
        'total': job.total_rows,
        'success': job.success_rows,
        'errors': job.error_rows,
        'status': job.status,
        'preview': preview[:50],
    })


@csrf_exempt
@require_POST
@roles_required(*ADMIN_ROLES)
def import_commit_view(request):
    text = request.body.decode('utf-8', 'replace')
    job, stats = services.import_commit(
        text, actor=getattr(request.user, 'login_name', '')
    )
    return JsonResponse({
        'ok': job.status == 'committed',
        'batch_id': str(job.batch_id),
        'status': job.status,
        'stats': stats,
    })


@require_http_methods(['GET'])
@roles_required(*TEACHER_ROLES)
def student_export(request):
    """受限 CSV 导出（对象/字段 scope 与列表一致）。

    ``?stream=1`` 使用 StreamingHttpResponse + 分批迭代，避免 10k 行
    一次性物化；默认仍返回完整响应以兼容既有调用方。
    """
    from django.http import HttpResponse, StreamingHttpResponse

    from smass_organization import export

    account = getattr(request, 'user', None)
    unit_code = request.GET.get('unit')
    keyword = request.GET.get('q')
    limit = int(request.GET.get('limit', export.MAX_ROWS))
    offset = int(request.GET.get('offset', 0))

    if request.GET.get('stream') == '1':
        total = export.count_students(
            account, unit_code=unit_code, keyword=keyword)
        chunks = export.iter_students_csv(
            account, unit_code=unit_code, keyword=keyword,
            limit=limit, offset=offset)
        response = StreamingHttpResponse(
            chunks, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="students.csv"'
        response['X-Streamed'] = '1'
        response['X-Total-Rows'] = str(total)
        response['X-Exported-Rows'] = str(max(min(total - offset, limit), 0))
        return response

    text, meta = export.export_students_csv(
        account,
        unit_code=unit_code,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )

    response = HttpResponse(text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="students.csv"'
    response['X-Exported-Rows'] = str(meta['exported'])
    response['X-Total-Rows'] = str(meta['total'])
    return response
