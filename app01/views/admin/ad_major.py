"""专业信息后台。"""
import urllib.parse

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from app01 import models
from app01.form.admin_inter import MajorModelForm
from app01.services import crud, imports
from app01.utils.authz import admin_required
from app01.utils.pagination import Pagination

SEARCH_FIELDS = ('name', 'college__name')

STR_DICT = {'name_ch': '专业', 'name_en': 'major'}


@admin_required
def major_list(request):
    """ 专业列表 """
    keyword = request.GET.get('search', '')
    queryset = crud.apply_search(
        models.Major.objects.select_related('college').order_by('id'),
        SEARCH_FIELDS,
        keyword,
    )

    page_object = Pagination(request, queryset)

    context = {
        'form': MajorModelForm(),
        'str_dict': STR_DICT,
        'endpoints': crud.build_endpoints('major'),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'admin/major.html', context)


@admin_required
@require_POST
def major_add(request):
    """ 添加专业（ajax 请求） """
    form = MajorModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
def major_detail(request):
    """ 根据主键获取专业信息 """
    uid = request.GET.get('uid')
    row = crud.row_detail_dict(models.Major, uid)
    if row is None:
        return JsonResponse({'status': False, 'error': '数据不存在'}, status=404)
    return JsonResponse({'status': True, 'data': row})


@admin_required
@require_POST
def major_edit(request):
    """ 编辑专业（ajax 请求） """
    uid = request.GET.get('uid')
    instance = models.Major.objects.filter(pk=uid).first()
    if instance is None:
        return JsonResponse({'status': False, 'tips': '数据不存在'}, status=404)

    form = MajorModelForm(data=request.POST, instance=instance)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})
    form.save()
    return JsonResponse({'status': True})


@admin_required
@require_POST
def major_delete(request):
    """ 删除专业（ajax 请求） """
    uid = request.GET.get('uid') or request.POST.get('uid')
    return crud.delete_by_pk(models.Major, uid, request)


@admin_required
def major_download_template(request):
    """ 下载【批量添加专业】模版 """
    workbook = Workbook()
    sheet = workbook.active
    for col_num, header in enumerate(imports.MAJOR_HEADERS, 1):
        sheet['{}1'.format(get_column_letter(col_num))] = header

    filename = '专业信息批量导入模版.xlsx'
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'{}'.format(
        urllib.parse.quote(filename)
    )
    workbook.save(response)
    return response


@admin_required
@require_POST
def major_multi(request):
    """ 批量添加专业（Excel 文件上传，整批原子） """
    file_object = request.FILES.get('excel_template')
    try:
        result = imports.import_majors(file_object)
    except imports.SheetError as exc:
        result = imports.ImportResult(errors=[str(exc)])

    return render(request, 'admin/import_result.html', {
        'str_dict': STR_DICT,
        'result': result,
        'list_url': '/admin/major/list/',
        'template_url': '/admin/major/download/template/',
    })
