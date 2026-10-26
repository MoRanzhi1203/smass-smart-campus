import urllib.parse

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from openpyxl.reader.excel import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl import Workbook

from app01 import models
from app01.form.admin_inter import StudentModelForm
from app01.utils.encrypt import md5
from app01.utils.formatchange import Delete_ForeignKey_id, row_delete, row_obtain, row_resetPass
from app01.utils.pagination import Pagination


def student_list(request):
    """ 学生列表 """

    # 构造搜索
    data_dict = {}  # 声明变量
    search_data = request.GET.get('search', '')  # 获取输入值
    if search_data:
        data_dict['name__contains'] = search_data  # 封装字典：包含输入值
    # 根据搜索条件去数据库获取
    queryset = models.Student.objects.filter(**data_dict)

    # 获取各字段的ModelForm方法bs样式
    form = StudentModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '学生',
        'name_en': 'student',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/student.html', context)


@csrf_exempt
def student_add(request):
    """ 添加学生（ajax请求） """

    form = StudentModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def student_detail(request):
    """ 根据ID获取学生信息 """

    uid = request.GET.get('uid')
    # 获取匹配过滤条件的行数据
    row_dict = models.Student.objects.filter(id=uid).values().first()
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 对外键字段名最后附加的'_id'进行删除
    Delete_ForeignKey_id(row_dict, models.Student)

    # 构建响应数据
    result = {
        'status': True,
        'data': row_dict
    }
    return JsonResponse(result)


@csrf_exempt
def student_edit(request):
    """ 编辑学生（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.Student.objects.filter(id=uid).first()

    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = StudentModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def student_delete(request):
    """ 删除学生（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.Student)


def student_obtain(request):
    """ 获取重置学生信息 """

    uid = request.GET.get('uid')

    return row_obtain(uid, models.Student)


def student_resetPass(request):
    """ 重置学生账号密码 """

    uid = request.GET.get('uid')

    return row_resetPass(uid, models.Student)


def student_download_template(request):
    """ 下载【批量添加学生账号】模版 """

    # 创建工作簿
    workbook = Workbook()
    sheet = workbook.active

    # 表头内容列表
    headers = ['学号', '姓名', '性别', '民族', '身份证号', '手机号', 'QQ号', '详细地址', '楼栋', '寝室号']

    # 批量添加表头
    for col_num, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_num)
        sheet[f'{col_letter}1'] = header

    # 设置响应头以指定文件名和内容类型
    filename = '学生信息批量导入模版.xlsx'
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename*=UTF-8\'\'{}'.format(urllib.parse.quote(filename))

    # 将工作簿保存到响应对象中
    workbook.save(response)

    return response


def student_multi(request):
    """ 批量添加学生信息（Excel文件上传） """

    # 1.获取用户上传的文件
    file_object = request.FILES.get('excel_template')
    # if request.method == 'POST' and request.FILES.get('excel_file'):
    #     file_object = request.FILES['excel_file']

    if file_object:

        # 2.对象传递给 openpyxl，由 openpyxl 读取文件的内容
        workbook = load_workbook(file_object)
        sheet = workbook.active  # 获取活动（当前显示）的工作表
        # sheet = workbook.worksheets[0]
        # sheet = workbook['Sheet1']  # 通过工作表名称获取

        tmp_list = []
        # 3.循环获取每一行数据，values_only=True 只返回单元格的值
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # 获取每个值
            id = row[0]
            name = row[1]
            pinyin = row[2]

            sex_determine = row[3]
            if sex_determine == '男':
                sex = 0
            elif sex_determine == '女':
                sex = 1
            else:
                # 处理未知性别值的情况
                sex = None

            nation = row[4]

            cardID = str(row[5])
            phone = row[6]
            qq = row[7]

            password = '123456'

            address = row[8]
            # building = row[9]
            # dormitory = row[10]

            political_determine = row[9]
            if political_determine == '群众':
                political = 0
            elif political_determine == '团员':
                political = 1
            elif political_determine == '党员':
                political = 2
            else:
                # 处理未知性别值的情况
                political = None

            major_name = row[11]
            major = models.Major.objects.get(name=major_name)
            classes_name = row[12]
            classes = models.Classes.objects.get(name=classes_name, major=major)

            data = {
                'id': id,
                'name': name,
                'password': password,
                'pinyin': pinyin,
                'sex': sex,
                'nation': nation,
                'classes': classes,
                'cardID': cardID,
                'phone': phone,
                'qq': qq,
                'address': address,
                # 'building': building,
                # 'dormitory': dormitory,
                'political': political,
            }

            # 判断该值是否存在
            exists = models.Student.objects.filter(id=id).exists()
            if not exists:
                # 追加数据行
                tmp_list.append(models.Student(**data))

        # 添加到数据库
        models.Student.objects.bulk_create(tmp_list)

        return redirect('/admin/student/list/')

    else:
        return JsonResponse({'message': '未接收到文件'}, status=400)


def all_delete(request):
    """ 清空学生表 """

    models.Student.objects.all().delete()

    return redirect('/admin/student/list/')