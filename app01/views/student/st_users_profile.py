import re

from django.http import JsonResponse
from django.shortcuts import render

from app01 import models
from app01.form.admin_inter import StuChangePassModelForm
from app01.utils.encrypt import md5


def student_users_profile(request):
    """ 显示学生个人主页 """

    uid = request.session['info'].get('id')

    # 将对象转换为字典
    row_dict = models.Student.objects.filter(id=uid)

    # 获取各字段的ModelForm方法bs样式
    form = StuChangePassModelForm()

    committee_dict = models.ClassCommittee.objects.filter(id=uid)
    duties_dict = models.LeagueCadres.objects.filter(id=uid)

    context = {
        'data': row_dict,
        'form': form,
        'committee_dict': committee_dict,
        'duties_dict': duties_dict,
    }

    print(context)

    return render(request, 'student/users-profile.html', context)


def student_change_password(request):
    """ 学生账号修改密码 """

    # 获取该用户在Student表中的'id'
    uid = request.session.get('info')['id']
    # print(uid)

    # 接收表单传值：password, new_password, confirm_password
    form = StuChangePassModelForm(data=request.POST)
    print(form)

    # 0.检验表单是否有效
    if form.is_valid():
        # 获取在Student表中的原密码
        row_password = models.Student.objects.filter(id=uid).values('password').first()

        past_password = form.data['past_password']
        # 对表单传值的原密码进行加密
        past_password_md5 = md5(past_password)

        # 1.检验表单传值的原密码是否正确
        if not row_password['password'] == past_password_md5:
            return JsonResponse({'status': False, 'error': '原密码错误', 'tips': 1})
        else:
            new_password = form.data['new_password']

            # 2.检验表单传值的新旧密码是否重复
            if past_password == new_password:
                return JsonResponse({'status': False, 'error': '新旧密码重复', 'tips': 2})
            else:
                confirm_password = form.data['confirm_password']

                # 3.检验表单传值的new_password与confirm_password是否一致
                if not new_password == confirm_password:
                    return JsonResponse({'status': False, 'error': '两次输入不一致', 'tips': 3})

                # 4.检验新密码是否为6到10位
                elif len(new_password) < 6 or len(new_password) > 10:
                    return JsonResponse({'status': False, 'error': '密码应为6-10位', 'tips': 4})

                else:
                    pattern = r'^[a-zA-Z0-9]+$'
                    match = re.match(pattern, new_password)

                    # 5.检验新密码是否仅包含数字与大小写字母
                    if not match:
                        return JsonResponse({'status': False, 'error': '密码仅包含数字与大小写字母', 'tips': 4})

                    else:
                        # 修改密码至 Student数据表
                        student = models.Student.objects.get(id=uid)
                        student.password = new_password
                        student.save()
                        return JsonResponse({'status': True})

    return JsonResponse({'status': False, 'error': form.errors})
