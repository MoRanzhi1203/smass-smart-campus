from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from openpyxl.reader.excel import load_workbook

from app01 import models
from app01.form.admin_inter import ClassesModelForm
from app01.utils.formatchange import Delete_ForeignKey_id, row_delete, download_template
from app01.utils.pagination import Pagination


def classes_list(request):
    """ 班级列表 """

    # 构造搜索
    data_dict = {}  # 声明变量
    search_data = request.GET.get('search', '')  # 获取输入值
    if search_data:
        data_dict['name__contains'] = search_data  # 封装字典：包含输入值
    # 根据搜索条件去数据库获取
    queryset = models.Classes.objects.filter(**data_dict)

    # 获取各字段的ModelForm方法bs样式
    form = ClassesModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '班级',
        'name_en': 'classes',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/classes.html', context)


@csrf_exempt
def classes_add(request):
    """ 添加班级（ajax请求） """

    form = ClassesModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def classes_detail(request):
    """ 根据ID获取教师信息 """

    uid = request.GET.get('uid')
    # 获取匹配过滤条件的行数据
    row_dict = models.Classes.objects.filter(id=uid).values().first()
    print(row_dict)
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 对外键字段名最后附加的'_id'进行删除
    Delete_ForeignKey_id(row_dict, models.Classes)
    print(row_dict)

    # 构建响应数据
    result = {
        'status': True,
        'data': row_dict
    }
    return JsonResponse(result)


@csrf_exempt
def classes_edit(request):
    """ 编辑班级（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.Classes.objects.filter(id=uid).first()

    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = ClassesModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def classes_delete(request):
    """ 删除班级（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.Classes)


def classes_download_template(request):
    """ 下载【批量添加班级】模版 """

    # 表头内容列表
    headers = ['学院', '专业', '年级', '班级', '辅导员', '教师编号']

    # 创建并下载表格
    response = download_template(headers=headers, head_txt='班级')

    return response


def classes_multi(request):
    """ 批量添加班级信息（Excel文件上传） """

    # 1.获取用户上传的文件
    file_object = request.FILES.get('excel_template')

    if file_object:
        # 2.对象传递给 openpyxl，由 openpyxl 读取文件的内容
        workbook = load_workbook(file_object)
        sheet = workbook.active  # 获取活动（当前显示）的工作表

        tmp_list = []
        # 3.循环获取每一行数据，values_only=True 只返回单元格的值
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # 获取每个值

            major_name = row[1]
            major = models.Major.objects.get(name=major_name)

            grade_name = row[2]
            grade = models.Grade.objects.get(name=grade_name)

            name = row[3]

            counsellor_id = row[5]
            counsellor = models.Teacher.objects.get(id=counsellor_id)

            data = {
                'major': major,
                'grade': grade,
                'name': name,
                'counsellor': counsellor,
            }

            # 判断该值是否存在
            exists = models.Classes.objects.filter(major=major, name=name).exists()
            if not exists:
                # 追加数据行
                tmp_list.append(models.Classes(**data))

            # 添加到数据库
        models.Classes.objects.bulk_create(tmp_list)

    return redirect('/admin/classes/list/')


def all_delete(request):
    """ 清空班级表 """

    models.Classes.objects.all().delete()

    return redirect('/admin/classes/list/')
