from django.shortcuts import render

from app01 import models
from app01.utils.NicePagination import Pagination


def classes_list(request):
    """ """

    uid = request.session['info'].get('id')

    # row_dict = models.Student.objects.filter(id=uid).values()
    row_dict = models.Student.objects.filter(id=uid)

    classes = models.Student.objects.filter(id=uid).values('classes')

    # 构造搜索
    data_dict = {}  # 声明变量
    search_data = request.GET.get('search', '')  # 获取输入值
    if search_data:
        data_dict['name__contains'] = search_data  # 封装字典：包含输入值
    # 根据搜索条件去数据库获取
    queryset = models.Student.objects.filter(classes__in=classes, **data_dict)

    # 分页
    page_object = Pagination(request, queryset)

    context = {
        'row_dict': row_dict,
        # 'data': data,
        'queryset': page_object.page_queryset,  # 分页数据
        'page_string': page_object.html(),  # 生成页码
    }

    return render(request, 'student/classes-list.html', context)