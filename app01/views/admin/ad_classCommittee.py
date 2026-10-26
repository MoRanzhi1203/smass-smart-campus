from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from app01 import models
from app01.form.admin_inter import ClassCommitteeModelForm
from app01.utils.formatchange import row_delete
from app01.utils.pagination import Pagination


def classCommittee_list(request):
    """ 团学干部列表 """

    # 构造搜索
    data_dict = {}  # 声明变量
    search_data = request.GET.get('search', '')  # 获取输入值
    if search_data:
        data_dict['name__contains'] = search_data  # 封装字典：包含输入值
    # 根据搜索条件去数据库获取
    queryset = models.ClassCommittee.objects.filter(**data_dict)

    # 获取各字段的ModelForm方法bs样式
    form = ClassCommitteeModelForm()

    # 页面传参
    str_dict = {
        'name_ch': '班委干部',
        'name_en': 'leagueCadres',
    }

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'form': form,
        'str_dict': str_dict,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'admin/classCommittee.html', context)


@csrf_exempt
def classCommittee_add(request):
    """ 添加成员（ajax请求） """

    form = ClassCommitteeModelForm(data=request.POST)
    if form.is_valid():
        # 保存到数据库
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def classCommittee_detail(request):
    """ 根据ID获取成员信息 """

    uid = request.GET.get('uid')
    # 将对象转换为字典
    row_dict = models.ClassCommittee.objects.filter(id=uid).values().first()
    # print(row_dict)
    if not row_dict:
        return JsonResponse({'status': False, 'error': '数据不存在'})

    # 从数据库中获取到了一个对象 row_object
    result = {
        'status': True,
        'data': row_dict,
    }
    return JsonResponse(result)


@csrf_exempt
def classCommittee_edit(request):
    """ 编辑成员信息（ajax请求） """

    uid = request.GET.get('uid')
    row_object = models.ClassCommittee.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在'})

    form = ClassCommitteeModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})


def classCommittee_delete(request):
    """ 删除成员信息（ajax请求） """

    uid = request.GET.get('uid')

    return row_delete(uid, models.Department)