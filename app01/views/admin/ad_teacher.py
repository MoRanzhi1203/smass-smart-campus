import re

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from openpyxl.reader.excel import load_workbook

from app01 import models
from app01.form.admin_inter import TeacherModelForm
from app01.utils.encrypt import md5
from app01.utils.formatchange import Delete_ForeignKey_id, row_delete, row_obtain, download_template
from app01.utils.pagination import Pagination


def teacher_list(request):
    """ 教师列表 """

    # 构造搜索
    data_dict = {}  # 声明变量
    search_data = request.GET.get('search', '')  # 获取输入值
    if search_data:
        data_dict['name__contains'] = search_data  # 封装字典：包含输入值
    # 根据搜索条件去数据库获取
    queryset = models.Teacher.objects.filter(**data_dict)

    # 获取各字段的ModelForm方法bs样式
    form = TeacherModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '教师',
        'name_en': 'teacher',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/teacher.html', context)


@csrf_exempt
def teacher_add(request):
    """ 添加教师（ajax请求） """

    form = TeacherModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def teacher_detail(request):
    """ 根据ID获取教师信息 """

    uid = request.GET.get('uid')
    # 获取匹配过滤条件的行数据
    row_dict = models.Teacher.objects.filter(id=uid).values().first()
    # print(row_dict)
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 对外键字段名最后附加的'_id'进行删除
    Delete_ForeignKey_id(row_dict, models.Teacher)
    # print(row_dict)

    # 构建响应数据
    result = {
        'status': True,
        'data': row_dict
    }
    return JsonResponse(result)


@csrf_exempt
def teacher_edit(request):
    """ 编辑教师（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.Teacher.objects.filter(id=uid).first()

    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = TeacherModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def teacher_delete(request):
    """ 删除教师（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.Teacher)


def teacher_obtain(request):
    """ 获取重置教师信息 """

    uid = request.GET.get('uid')

    return row_obtain(uid, models.Teacher)


def teacher_resetPass(request):
    """ 重置教师账号密码 """

    uid = request.GET.get('uid')
    reset = models.Teacher.objects.get(id=uid)
    # 重置密码为身份证后六位，并 md5加密
    reset.password = md5(reset.cardID[-6:])
    # 保存至数据库
    reset.save()

    # 密码重置成功
    return JsonResponse({'status': True})


def teacher_download_template(request):
    """ 下载【批量添加教师信息】模版 """

    # 表头内容列表
    headers = '教师编号、姓名、拼音、性别、民族、身份证号码、手机号、QQ号、详细地址、入职时间、教师职务、院系、政治面貌'.split('、')

    # 创建并下载表格
    response = download_template(headers=headers, head_txt='教师')

    return response


def teacher_multi(request):
    """ 批量添加教师信息（Excel文件上传） """

    # 1.获取用户上传的文件
    file_object = request.FILES.get('excel_template')

    if file_object:

        # 2.对象传递给 openpyxl，由 openpyxl 读取文件的内容
        workbook = load_workbook(file_object)
        sheet = workbook.active  # 获取活动（当前显示）的工作表

        tmp_teacher_list = []
        tmp_teacherPosition_list = []
        # 3.循环获取每一行数据，values_only=True 只返回单元格的值
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # print(row)
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
            phone = str(row[6])
            qq = str(row[7])

            password = md5('123456')

            address = row[8]
            entry_time = row[9]

            # 清除字符串中的空格
            position_string = row[10].replace(" ", "")
            # 根据中文逗号和英文逗号分割字符串为列表
            position_list = re.split(r"[,，]", position_string)
            # 创建一个空列表来保存外键值
            position_ids = []
            # 遍历 position_list 列表
            for position_name in position_list:
                # 根据 name 属性获取 Position 实例
                position = models.Position.objects.get(name=position_name)
                # 获取 Position 实例的外键值并添加到 position_ids 列表中
                position_ids.append(position.id)

            college_name = row[11]
            college = models.College.objects.get(name=college_name)

            political_determine = row[12]
            if political_determine == '群众':
                political = 0
            elif political_determine == '团员':
                political = 1
            elif political_determine == '党员':
                political = 2
            else:
                # 处理未知性别值的情况
                political = None

            # print(position_ids)

            data = {
                'id': id,
                'name': name,
                'password': password,
                'pinyin': pinyin,
                'sex': sex,
                'nation': nation,
                'cardID': cardID,
                'phone': phone,
                'qq': qq,
                'address': address,
                'entry_time': entry_time,
                # 'position': position_ids,
                'college': college,
                'political': political,
            }

            exists = models.Teacher.objects.filter(id=id).exists()
            if not exists:
                # 追加数据行
                tmp_teacher_list.append(models.Teacher(**data))

            print(position_ids)
            for ele in position_ids:
                data_teaPos = {
                    'teacher_id': id,
                    'position_id': ele,
                }

                exists_tp = models.TeacherPosition.objects.filter(teacher_id=id, position_id=ele).exists()

                if not exists_tp:
                    # 追加数据行
                    tmp_teacherPosition_list.append(models.TeacherPosition(**data_teaPos))

        # 添加到数据库
        models.Teacher.objects.bulk_create(tmp_teacher_list)
        models.TeacherPosition.objects.bulk_create(tmp_teacherPosition_list)

        # # 获取 ModelA 的实例
        # position_id = models.Position.objects.get(id=model_a_id)
        # # 创建多对多关系对象的列表
        # modela_modelb_instances = []
        # # 遍历 ModelB 实例列表
        # for teacher_id in models.Teacher.objects:
        #     # 创建中间表对象，设置关联字段
        #     modela_modelb_instance = models.TeacherPosition(teacher=teacher_id, position = position_id)
        #     # 将对象添加到列表中
        #     modela_modelb_instances.append(modela_modelb_instance)
        #
        # # 使用 bulk_create() 方法将多对多关系的对象列表一次性批量添加到中间表
        # models.TeacherPosition.objects.bulk_create(modela_modelb_instances)

        return redirect('/admin/teacher/list/')


def all_delete(request):
    """ 清空教师表 """

    models.Teacher.objects.all().delete()

    return redirect('/admin/teacher/list/')
