import urllib.parse

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from openpyxl import Workbook
from openpyxl.reader.excel import load_workbook
from openpyxl.utils import get_column_letter

from app01 import models
from app01.form.admin_inter import CollegeModelForm
from app01.utils.formatchange import row_delete, download_template
from app01.utils.pagination import Pagination


def college_list(request):
    """ 学院列表 """

    # 获取所有数据行
    queryset = models.College.objects.all()

    # 获取各字段的ModelForm方法bs样式
    form = CollegeModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '学院',
        'name_en': 'college',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/college.html', context)


@csrf_exempt
def college_add(request):
    """ 添加学院（ajax请求） """

    form = CollegeModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def college_detail(request):
    """ 根据ID获取学院信息 """

    uid = request.GET.get('uid')
    # 获取匹配过滤条件的行数据
    row_dict = models.College.objects.filter(id=uid).values().first()
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 构建响应数据
    result = {
        'status': True,
        'data': row_dict
    }
    return JsonResponse(result)


def college_edit(request):
    """ 编辑学院（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.College.objects.filter(id=uid).first()

    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = CollegeModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def college_delete(request):
    """ 删除学院（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.College)


def college_download_template(request):
    """ 下载【批量添加学院】模版 """

    # 表头内容列表
    headers = ['学院']

    # 创建并下载表格
    response = download_template(headers=headers, head_txt='学院')

    return response


def college_multi(request):
    """ 批量添加学院（Excel文件上传） """

    # 1.获取用户上传的文件
    file_object = request.FILES.get('excel_template')

    if file_object:

        # 2.对象传递给 openpyxl，由 openpyxl 读取文件的内容
        workbook = load_workbook(file_object)
        sheet = workbook.active  # 获取活动（当前显示）的工作表

        tmp_list = []
        # 3.循环获取每一行数据，values_only=True 只返回单元格的值
        for row in sheet.iter_rows(min_row=2, values_only=True):
            name = row[0]

            data = {
                'name': name,
            }

            # 判断该值是否存在
            exists = models.College.objects.filter(name=name).exists()
            if not exists:
                # 追加数据行
                tmp_list.append(models.College(**data))

        # 添加到数据库
        models.College.objects.bulk_create(tmp_list)

        return redirect('/admin/college/list/')
