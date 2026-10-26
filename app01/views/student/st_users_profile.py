"""学生个人主页与改密。"""
import re

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app01 import models
from app01.form.admin_inter import StuChangePassModelForm
from app01.services import accounts
from app01.utils.authz import student_required

#: 业务规定的密码格式（保持与历史前端提示一致）
_PASSWORD_PATTERN = re.compile(r'^[a-zA-Z0-9]+$')
_PASSWORD_MIN_LEN = 6
_PASSWORD_MAX_LEN = 10


@student_required
def student_users_profile(request):
    """ 显示学生个人主页（身份只取自服务端会话） """
    uid = (request.session.get('info') or {}).get('id')

    student = (
        models.Student.objects
        .select_related('classes', 'classes__major', 'classes__major__college')
        .filter(pk=uid)
        .first()
    )

    context = {
        'data': [student] if student else [],
        'form': StuChangePassModelForm(),
        'committee_dict': models.ClassCommittee.objects.filter(id=uid),
        'duties_dict': models.LeagueCadres.objects.select_related('department').filter(id=uid),
    }
    return render(request, 'student/users-profile.html', context)


@student_required
@require_POST
def student_change_password(request):
    """ 学生账号修改密码

    - 原密码校验走 ``accounts.verify_password``（兼容历史 MD5 并自动升级）；
    - 新密码统一由 ``accounts.set_password`` 编码，绝不明文入库。
    """
    uid = (request.session.get('info') or {}).get('id')
    student = models.Student.objects.filter(pk=uid).first()
    if student is None:
        return JsonResponse({'status': False, 'error': '账号不存在'}, status=404)

    form = StuChangePassModelForm(data=request.POST)
    if not form.is_valid():
        return JsonResponse({'status': False, 'error': form.errors})

    past_password = form.cleaned_data['past_password']
    new_password = form.cleaned_data['new_password']
    confirm_password = form.cleaned_data['confirm_password']

    # 1. 原密码是否正确
    if not accounts.verify_password(student, past_password):
        return JsonResponse({'status': False, 'error': '原密码错误', 'tips': 1})

    # 2. 新旧密码是否重复
    if past_password == new_password:
        return JsonResponse({'status': False, 'error': '新旧密码重复', 'tips': 2})

    # 3. 两次输入是否一致
    if new_password != confirm_password:
        return JsonResponse({'status': False, 'error': '两次输入不一致', 'tips': 3})

    # 4. 长度与字符集
    if not (_PASSWORD_MIN_LEN <= len(new_password) <= _PASSWORD_MAX_LEN):
        return JsonResponse(
            {'status': False, 'error': '密码应为{}-{}位'.format(_PASSWORD_MIN_LEN, _PASSWORD_MAX_LEN),
             'tips': 4}
        )
    if not _PASSWORD_PATTERN.match(new_password):
        return JsonResponse(
            {'status': False, 'error': '密码仅包含数字与大小写字母', 'tips': 4}
        )

    # 5. 落库（官方哈希）
    accounts.set_password(student, new_password)
    accounts.log_action(request, 'password_change', student)
    return JsonResponse({'status': True})
