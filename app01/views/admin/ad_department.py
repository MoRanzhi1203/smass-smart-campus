"""学生部门后台。

搜索字段修正：``Department`` 的字段名是 ``department``，不是 ``name``。
历史版本统一用 ``name__contains``，一搜索就会 ``FieldError``。
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app01 import models
from app01.form.admin_inter import DepartmentModelForm
from app01.services import crud
from app01.utils.authz import admin_required
from app01.utils.pagination import Pagination

SEARCH_FIELDS = ('department', 'college__name')

STR_DICT = {'name_ch': '部门', 'name_en': 'department'}


@admin_required
def department_list(request):
    """ 部门列表 """
    keyword = request.GET.get('search', '')
    queryset = crud.apply_search(
        models.Department.objects.select_related('college').order_by('id'),
        SEARCH_FIELDS,
        keyword,
    )

    page_object = Pagination(request, queryset)

    context = {
        'form': DepartmentModelForm(),
        'str_dict': STR_DICT,
        'endpoints': crud.build_endpoints('department'),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'admin/department.html', context)


@admin_required
@require_POST
def department_add(request):
    """ 添加部门（ajax 请求） """
    form = DepartmentModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
def department_detail(request):
    """ 根据主键获取部门信息 """
    uid = request.GET.get('uid')
    row = crud.row_detail_dict(models.Department, uid)
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


@admin_required
@require_POST
def department_edit(request):
    """ 编辑部门信息（ajax 请求） """
    uid = request.GET.get('uid')
    instance = models.Department.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'tips': '数据不存在'}, status=404)

    form = DepartmentModelForm(data=request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
@require_POST
def department_delete(request):
    """ 删除部门信息（ajax 请求） """
    uid = request.GET.get('uid') or request.POST.get('uid')
    return crud.delete_by_pk(models.Department, uid, request)
