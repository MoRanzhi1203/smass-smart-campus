import urllib.parse

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from openpyxl.reader.excel import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app01 import models
from app01.form.admin_inter import MajorModelForm
from app01.utils.formatchange import row_delete
from app01.utils.pagination import Pagination


def major_list(request):
    """ 专业列表 """

    # 获取所有数据行
    queryset = models.Major.objects.all()

    # 获取各字段的ModelForm方式bs样式
    form = MajorModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '专业',
        'name_en': 'major',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/major.html', context)


@csrf_exempt
def major_add(request):
    """ 添加学院（ajax请求） """

    form = MajorModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def major_detail(request):
    """ 根据ID获取学院信息 """

    uid = request.GET.get('uid')
    # 获取匹配过滤条件的行数据
    row_dict = models.Major.objects.filter(id=uid).values().first()
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 构建响应数据
    result = {
        'status': True,
        'data': row_dict
    }
    return JsonResponse(result)


def major_edit(request):
    """ 编辑专业（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.Major.objects.filter(id=uid).first()

    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = MajorModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def major_delete(request):
    """ 删除专业（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.Major)


def major_download_template(request):
    """ 下载【批量添加学院】模版 """

    # 创建工作簿
    workbook = Workbook()
    sheet = workbook.active

    # 表头内容列表
    headers = ['学院', '专业']

    # 批量添加表头
    for col_num, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_num)
        sheet[f'{col_letter}1'] = header

    # 设置响应头以指定文件名和内容类型
    filename = '专业信息批量导入模版.xlsx'
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'{}'.format(urllib.parse.quote(filename))

    # 将工作簿保存到响应对象中
    workbook.save(response)

    return response


def major_multi(request):
    """ 批量添加专业（Excel文件上传） """

    # 1.获取用户上传的文件
    file_object = request.FILES.get('excel_template')

    if file_object:

        # 2.对象传递给 openpyxl，由 openpyxl 读取文件的内容
        workbook = load_workbook(file_object)
        sheet = workbook.active  # 获取活动（当前显示）的工作表

        tmp_list = []
        # 3.循环获取每一行数据，values_only=True 只返回单元格的值
        for row in sheet.iter_rows(min_row=2, values_only=True):

            college_mane = row[0]
            college = models.College.objects.get(name=college_mane)

            name = row[1]

            data = {
                'college': college,
                'name': name,
            }

            # 判断该值是否存在
            exists = models.Major.objects.filter(name=name).exists()
            if not exists:
                # 追加数据行
                tmp_list.append(models.Major(**data))

        # 添加到数据库
        models.Major.objects.bulk_create(tmp_list)

        return redirect('/admin/major/list/')
