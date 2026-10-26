"""学生查看本班同学列表。"""
from django.shortcuts import render

from app01 import models
from app01.services import crud
from app01.utils.authz import student_required
from app01.utils.NicePagination import Pagination

#: 学生端只允许按姓名 / 学号搜索，且仅限本班
SEARCH_FIELDS = ('name', 'id')


@student_required
def classes_list(request):
    """ 显示所在班级的学生列表

    作用域收窄：查询直接以"本人所属班级"为条件，学生无法通过改 ``uid`` 或参数
    查看其他班级的同学。
    """
    uid = (request.session.get('info') or {}).get('id')
    me = models.Student.objects.select_related('classes').filter(pk=uid).first()

    keyword = request.GET.get('search', '')

    if me is None or me.classes_id is None:
        queryset = models.Student.objects.none()
    else:
        queryset = models.Student.objects.filter(classes_id=me.classes_id).order_by('id')
        queryset = crud.apply_search(queryset, SEARCH_FIELDS, keyword)

    page_object = Pagination(request, queryset)

    context = {
        'row_dict': [me] if me else [],
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        **crud.build_search_meta(SEARCH_FIELDS, keyword),
    }
    return render(request, 'student/classes-list.html', context)
