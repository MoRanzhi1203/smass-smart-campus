"""教师基本信息页。"""
from django.shortcuts import render

from app01 import models
from app01.utils.authz import teacher_required


@teacher_required
def teacher_basic(request):
    """ 显示教师本人基本信息

    历史版本此视图无任何鉴权，且路由模板 ``teacher/basic.html`` 为空占位；
    现在身份从服务端会话读取，并补齐基本信息展示。
    """
    uid = (request.session.get('info') or {}).get('id')
    teacher = (
        models.Teacher.objects
        .select_related('college')
        .filter(pk=uid)
        .first()
    )

    return render(request, 'teacher/basic.html', {'teacher': teacher})
