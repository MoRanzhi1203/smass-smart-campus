"""班委干部后台。

修复点：
1. ``str_dict['name_en']`` 曾误写为 ``'leagueCadres'``，导致班委页面的增、删、改、
   查详情全部打到团学干部接口（典型的"接口串台"）。现改为 ``classCommittee``，
   并同时提供命名路由 ``endpoints``，模板不再依赖字符串拼接；
2. ``classCommittee_delete`` 曾误传 ``models.Department``；
3. ``ClassCommittee`` 没有 ``name`` 字段，搜索改用 ``id__name`` / ``classes__name``。
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app01 import models
from app01.form.admin_inter import ClassCommitteeModelForm
from app01.services import crud
from app01.utils.authz import admin_required
from app01.utils.pagination import Pagination

SEARCH_FIELDS = ('id__name', 'id__id', 'classes__name', 'classes__major__name')

STR_DICT = {'name_ch': '班委干部', 'name_en': 'classCommittee'}


@admin_required
def classCommittee_list(request):
    """ 班委干部列表 """
    keyword = request.GET.get('search', '')
    queryset = crud.apply_search(
        models.ClassCommittee.objects.select_related(
            'id', 'classes', 'classes__major'
        ).order_by('id'),
        SEARCH_FIELDS,
        keyword,
    )

    page_object = Pagination(request, queryset)

    context = {
        'form': ClassCommitteeModelForm(),
        'str_dict': STR_DICT,
        'endpoints': crud.build_endpoints('classCommittee'),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'admin/classCommittee.html', context)


@admin_required
@require_POST
def classCommittee_add(request):
    """ 添加班委（ajax 请求） """
    form = ClassCommitteeModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
def classCommittee_detail(request):
    """ 根据主键获取班委信息 """
    uid = request.GET.get('uid')
    row = crud.row_detail_dict(models.ClassCommittee, uid)
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


@admin_required
@require_POST
def classCommittee_edit(request):
    """ 编辑班委信息（ajax 请求） """
    uid = request.GET.get('uid')
    instance = models.ClassCommittee.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'tips': '数据不存在'}, status=404)

    form = ClassCommitteeModelForm(data=request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
@require_POST
def classCommittee_delete(request):
    """ 删除班委（ajax 请求）

    目标模型必须显式指定为 ``ClassCommittee``（历史缺陷：误用 ``Department``）。
    """
    uid = request.GET.get('uid') or request.POST.get('uid')
    return crud.delete_by_pk(models.ClassCommittee, uid, request)
