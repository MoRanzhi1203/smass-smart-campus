"""团学干部后台。

修复点：
1. ``leagueCadres_delete`` 曾误传 ``models.Department``，导致删团干实际去打部门表；
2. ``LeagueCadres`` 没有 ``name`` 字段，原搜索会 ``FieldError``，改用 ``id__name``
   （``id`` 是指向 ``Student`` 的 OneToOne，取其姓名/学号）。
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app01 import models
from app01.form.admin_inter import LeagueCadresModelForm
from app01.services import crud
from app01.utils.authz import admin_required
from app01.utils.pagination import Pagination

SEARCH_FIELDS = ('id__name', 'id__id', 'department__department')

STR_DICT = {'name_ch': '团学干部', 'name_en': 'leagueCadres'}


@admin_required
def leagueCadres_list(request):
    """ 团学干部列表 """
    keyword = request.GET.get('search', '')
    queryset = crud.apply_search(
        models.LeagueCadres.objects.select_related('id', 'department').order_by('id'),
        SEARCH_FIELDS,
        keyword,
    )

    page_object = Pagination(request, queryset)

    context = {
        'form': LeagueCadresModelForm(),
        'str_dict': STR_DICT,
        'endpoints': crud.build_endpoints('leagueCadres'),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'admin/leagueCadres.html', context)


@admin_required
@require_POST
def leagueCadres_add(request):
    """ 添加团学干部（ajax 请求） """
    form = LeagueCadresModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
def leagueCadres_detail(request):
    """ 根据主键获取团学干部信息 """
    uid = request.GET.get('uid')
    row = crud.row_detail_dict(models.LeagueCadres, uid)
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


@admin_required
@require_POST
def leagueCadres_edit(request):
    """ 编辑团学干部信息（ajax 请求） """
    uid = request.GET.get('uid')
    instance = models.LeagueCadres.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'tips': '数据不存在'}, status=404)

    form = LeagueCadresModelForm(data=request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
@require_POST
def leagueCadres_delete(request):
    """ 删除团学干部（ajax 请求）

    目标模型必须显式指定为 ``LeagueCadres``（历史缺陷：误用 ``Department``）。
    """
    uid = request.GET.get('uid') or request.POST.get('uid')
    return crud.delete_by_pk(models.LeagueCadres, uid, request)
