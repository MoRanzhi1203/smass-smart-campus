"""U3：R4 组织与学生的可交互页面视图。

每页遵循同一模式：GET 渲染表单 → POST 校验 → 调用既有服务 → 持久化 →
成功走 PRG（Post/Redirect/Get）并带 message，失败回填错误。

所有写操作都经过 `smass_organization.services`，不在此层另立规则。
"""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from smass_organization import services
from smass_organization.models import (
    DataImportJob,
    DataImportRowError,
    OrganizationUnit,
    StudentRecord,
)
from smass_organization.views import ADMIN_ROLES, COLLEGE_ROLES, TEACHER_ROLES, roles_required


#: 基础字段（非扩展字段）的编辑角色
BASE_EDIT_ROLES = {'system_admin', 'college_admin'}

#: 可读取详情的角色（学生可看自己）
DETAIL_ROLES = {'system_admin', 'college_admin', 'teacher', 'student'}


def _base_editable(account):
    """基础字段（name/status/unit）的可编辑集合，按角色判定。

    注意：``services.editable_fields`` 返回的是 ``StudentFieldDefinition``
    对象（扩展字段定义），不是基础字段名，因此不能用于此处。
    """
    roles = services.account_roles(account)
    if roles & BASE_EDIT_ROLES:
        return {'name', 'status', 'unit'}
    return set()


def _actor(request):
    account = getattr(request, 'user', None)
    return getattr(account, 'login_name', '') if account is not None else ''


def _post_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 组织单元
# ---------------------------------------------------------------------------
@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def unit_new(request):
    errors = {}
    form = {'code': '', 'name': '', 'unit_type': 'college', 'parent': '',
            'sort_order': '0'}

    if request.method == 'POST':
        form.update({
            'code': (request.POST.get('code') or '').strip(),
            'name': (request.POST.get('name') or '').strip(),
            'unit_type': (request.POST.get('unit_type') or '').strip(),
            'parent': (request.POST.get('parent') or '').strip(),
            'sort_order': (request.POST.get('sort_order') or '0').strip(),
        })

        if not form['code']:
            errors['code'] = '编码不能为空'
        if not form['name']:
            errors['name'] = '名称不能为空'
        if not form['unit_type']:
            errors['unit_type'] = '必须选择类型'

        parent = None
        if form['parent']:
            parent = OrganizationUnit.objects.filter(pk=_post_int(form['parent'])).first()
            if parent is None:
                errors['parent'] = '上级组织不存在'

        if not errors:
            try:
                with transaction.atomic():
                    unit = services.create_unit(
                        code=form['code'], name=form['name'],
                        unit_type=form['unit_type'], parent=parent,
                        sort_order=_post_int(form['sort_order'], 0) or 0,
                    )
            except IntegrityError:
                errors['general'] = '编码「{}」已存在，请换一个'.format(form['code'])
            except Exception as exc:  # noqa: BLE001
                errors['general'] = str(exc)
            else:
                messages.success(request, '组织「{}」已创建'.format(unit.name))
                return redirect('/r4/units/')

    return render(request, 'r4/unit_form.html', {
        'mode': 'new',
        'form': form,
        'errors': errors,
        'unit_types': ['college', 'major', 'class'],
        'candidates': OrganizationUnit.objects.order_by('code')[:300],
    })


@require_http_methods(['GET', 'POST'])
@roles_required(*ADMIN_ROLES)
def unit_edit(request, pk):
    unit = OrganizationUnit.objects.filter(pk=pk).first()
    if unit is None:
        return HttpResponse('组织不存在', status=404)

    errors = {}
    form = {'code': unit.code, 'name': unit.name, 'unit_type': unit.unit_type,
            'parent': str(unit.parent_id or ''), 'sort_order': str(unit.sort_order)}

    if request.method == 'POST':
        form.update({
            'name': (request.POST.get('name') or '').strip(),
            'parent': (request.POST.get('parent') or '').strip(),
            'sort_order': (request.POST.get('sort_order') or '0').strip(),
        })

        if not form['name']:
            errors['name'] = '名称不能为空'

        new_parent_id = _post_int(form['parent'])
        if not errors:
            try:
                with transaction.atomic():
                    if form['name'] != unit.name:
                        unit.name = form['name']
                        unit.save(update_fields=['name'])
                    if new_parent_id != unit.parent_id:
                        new_parent = (
                            OrganizationUnit.objects.filter(pk=new_parent_id).first()
                            if new_parent_id else None
                        )
                        services.move_unit(unit, new_parent, actor=_actor(request))
            except IntegrityError:
                errors['general'] = '保存冲突，请刷新后重试'
            except Exception as exc:  # noqa: BLE001
                errors['general'] = str(exc)
            else:
                messages.success(request, '组织「{}」已更新'.format(unit.name))
                return redirect('/r4/units/')

    candidates = OrganizationUnit.objects.exclude(pk=unit.pk).order_by('code')[:300]
    return render(request, 'r4/unit_form.html', {
        'mode': 'edit',
        'unit': unit,
        'form': form,
        'errors': errors,
        'unit_types': [unit.unit_type],
        'candidates': candidates,
    })


# ---------------------------------------------------------------------------
# 学生档案
# ---------------------------------------------------------------------------
@require_http_methods(['GET'])
@roles_required(*DETAIL_ROLES)
def student_detail_page(request, student_no):
    """学生详情页（HTML）。越权/不存在统一 404，避免探测。"""
    account = getattr(request, 'user', None)
    record = StudentRecord.objects.filter(student_no=student_no).select_related('unit').first()
    if record is None or not services.can_access_student(account, record):
        return HttpResponse('学生不存在或无权访问', status=404)

    return render(request, 'r4/student_detail.html', {
        'record': record,
        'editable': _base_editable(account),
        'visible': services.visible_fields(account),
        'extra': services.filtered_extra(record, account),
    })


@require_http_methods(['GET', 'POST'])
@roles_required(*COLLEGE_ROLES)
def student_edit(request, student_no):
    account = getattr(request, 'user', None)
    record = StudentRecord.objects.filter(student_no=student_no).select_related('unit').first()
    if record is None or not services.can_access_student(account, record):
        return HttpResponse('学生不存在或无权访问', status=404)

    editable = _base_editable(account)
    errors = {}
    form = {
        'name': record.name,
        'status': record.status,
        'unit': str(record.unit_id or ''),
        'version': str(record.version),
    }
    conflict = False

    if request.method == 'POST':
        form.update({
            'name': (request.POST.get('name') or '').strip(),
            'status': (request.POST.get('status') or '').strip(),
            'unit': (request.POST.get('unit') or '').strip(),
            'version': (request.POST.get('version') or '').strip(),
        })

        if 'name' in editable and not form['name']:
            errors['name'] = '姓名不能为空'

        unit = None
        if 'unit' in editable and form['unit']:
            unit = OrganizationUnit.objects.filter(pk=_post_int(form['unit'])).first()
            if unit is None:
                errors['unit'] = '组织不存在'

        expected = _post_int(form['version'])
        if expected is None:
            errors['general'] = '缺少版本号，请刷新页面重试'

        if not errors:
            try:
                record, _changes = services.update_student(
                    record,
                    name=form['name'] if 'name' in editable else None,
                    status=form['status'] if 'status' in editable else None,
                    unit=unit if 'unit' in editable else None,
                    expected_version=expected,
                    actor=_actor(request),
                )
            except services.ConcurrencyError:
                conflict = True
                errors['general'] = '该记录已被他人修改，请刷新后重试'
                record.refresh_from_db()
                form['version'] = str(record.version)
            except Exception as exc:  # noqa: BLE001
                errors['general'] = str(exc)
            else:
                messages.success(request, '学生「{}」已更新'.format(record.name))
                return redirect('/r4/students/{}/'.format(record.student_no))

    response = render(request, 'r4/student_form.html', {
        'record': record,
        'form': form,
        'errors': errors,
        'editable': editable,
        'conflict': conflict,
        'units': OrganizationUnit.objects.order_by('code')[:300],
        'statuses': sorted(services.VALID_STATUS),
    })
    if conflict:
        response.status_code = 409
    return response


# ---------------------------------------------------------------------------
# 导入（预览/提交）
# ---------------------------------------------------------------------------
@require_POST
@roles_required(*ADMIN_ROLES)
def import_commit_page(request):
    """导入提交：返回 JSON，供导入页 fetch 调用。"""
    import json

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'reason': '请求体不是合法 JSON'}, status=400)

    text = payload.get('csv') or ''
    if not text.strip():
        return JsonResponse({'ok': False, 'reason': '内容为空'}, status=400)

    job, stats = services.import_commit(text, actor=_actor(request))

    created = int(stats.get('created', 0))
    updated = int(stats.get('updated', 0))
    failed = int(stats.get('failed', 0))

    return JsonResponse({
        'ok': job.status != 'failed',
        'job_id': job.pk,
        'status': job.status,
        'result': {
            'created': created,
            'updated': updated,
            'skipped': failed,
            'invalid': failed,
            'total': created + updated + failed,
        },
    })
