"""管理员账号后台。

安全要点：
- 全部写接口仅接受 POST，并由 ``admin_required`` 做视图级准入；
- 删除接口禁止删除当前登录账号（避免把系统锁死）；
- 密码与哈希不进入详情响应、不进入日志。
"""
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app01 import models
from app01.form.admin_inter import AdminModelForm
from app01.services import accounts, crud
from app01.utils.authz import admin_required
from app01.utils.pagination import Pagination

#: 管理员可见的搜索字段（显式声明，禁止拼接用户输入为字段名）
SEARCH_FIELDS = ('name', 'id')

STR_DICT = {'name_ch': '管理员', 'name_en': 'admin'}


@admin_required
def admin_list(request):
    """ 管理员列表 """
    keyword = request.GET.get('search', '')
    queryset = crud.apply_search(
        models.Admin.objects.all().order_by('id'), SEARCH_FIELDS, keyword
    )

    page_object = Pagination(request, queryset)

    context = {
        'form': AdminModelForm(),
        'str_dict': STR_DICT,
        'endpoints': crud.build_endpoints('admin'),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'admin/admin.html', context)


@admin_required
@require_POST
def admin_add(request):
    """ 添加管理员（ajax 请求） """
    form = AdminModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})

    account, raw_password, generated = accounts.save_account_form(
        form, models.Admin, request=request
    )

    result = {'status': True}
    if generated:
        # 明文只返回一次，供操作者转达；不写入日志
        result['initial_password'] = raw_password
    return JsonResponse(result)


@admin_required
def admin_detail(request):
    """ 根据主键获取管理员信息（不返回密码哈希） """
    uid = request.GET.get('uid')
    row = crud.row_detail_dict(models.Admin, uid, exclude=('password',))
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


@admin_required
@require_POST
def admin_edit(request):
    """ 编辑管理员（ajax 请求；密码留空表示不修改） """
    uid = request.GET.get('uid')
    instance = models.Admin.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'tips': '数据不存在'}, status=404)

    form = AdminModelForm(data=request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})

    accounts.save_account_form(form, models.Admin, instance=instance, request=request)
    return JsonResponse({'status': True})


@admin_required
@require_POST
def admin_delete(request):
    """ 删除管理员（ajax 请求） """
    uid = request.GET.get('uid') or request.POST.get('uid')
    current_id = (request.session.get('info') or {}).get('id')
    if uid is not None and str(uid) == str(current_id):
        return JsonResponse(
            {'status': False, 'error': '不能删除当前登录的账号'}, status=400
        )
    return crud.delete_by_pk(models.Admin, uid, request)


@admin_required
@require_POST
def admin_resetPass(request):
    """ 重置管理员密码（生成随机一次性密码并返回一次） """
    uid = request.GET.get('uid') or request.POST.get('uid')
    instance = models.Admin.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)

    raw_password = accounts.reset_password(instance, request=request)
    return JsonResponse({'status': True, 'password': raw_password})
