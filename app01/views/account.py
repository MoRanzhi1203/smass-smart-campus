from django.http import HttpResponse
from django.shortcuts import render, redirect

from app01 import models
from app01.form.account import AdminLoginForm, StudentLoginForm


def login(request):
    """ 登录主页面 """

    return render(request, 'login/index.html')


#############################################################

def login_admin(request):
    """ 管理员账号登录界面 """

    if request.method == 'GET':
        data = {
            'form': AdminLoginForm(),
            'name_ch': '管理员',
        }
        return render(request, 'login/login.html', data)

    form = AdminLoginForm(data=request.POST)
    if form.is_valid():
        # 验证成功，获取到的用户名和密码
        # {'username': '001', 'password': '123456'}
        # {'username': '001', 'password': '4fe0c3103f4ba88b66df31d81fde9bb0'}

        # 验证码的校验
        # 取出code值的同时在 dict 中将其剔除
        # user_input_code = form.cleaned_data.pop('code')
        # code = request.session.get('image_code', '')
        # if code.upper() != user_input_code.upper():
        #     form.add_error('code', '验证码错误')
        #     return render(request, 'login/login.html', {'form': form})

        # 去数据库校验用户名和密码是否正确，获取用户对象
        admin_object = models.Admin.objects.filter(**form.cleaned_data).first()
        print(admin_object)
        if not admin_object:
            form.add_error('password', '用户名或密码错误')
            return render(request, 'login/login.html', {'form': form})

        # 用户名和密码正确
        # 网站生成水机字符串，写到用户浏览器的Cookie中，再写入到Session中
        request.session['info'] = {
            'id': admin_object.id,
            'name': admin_object.name,
            'type': 'admin',
        }
        # 重置session超时时间，即下次登录时间为：七天后
        request.session.set_expiry(60 * 60 * 24)

        return redirect('/admin/admin/list/')

    data = {
        'form': AdminLoginForm(),
        'name_ch': '管理员',
    }

    return render(request, 'login/login.html', data)


def login_student(request):
    """ 学生账号登录界面 """

    if request.method == 'GET':
        data = {
            'form': StudentLoginForm(),
            'name_ch': '学生',
        }
        return render(request, 'login/login.html', data)

    form = StudentLoginForm(data=request.POST)
    if form.is_valid():
        # 验证成功，获取到的用户名和密码
        # {'username': '001', 'password': '123456'}
        # {'username': '001', 'password': '4fe0c3103f4ba88b66df31d81fde9bb0'}

        # 验证码的校验
        # 取出code值的同时在 dict 中将其剔除
        # user_input_code = form.cleaned_data.pop('code')
        # code = request.session.get('image_code', '')
        # if code.upper() != user_input_code.upper():
        #     form.add_error('code', '验证码错误')
        #     return render(request, 'login/login.html', {'form': form})

        # 去数据库校验用户名和密码是否正确，获取用户对象
        admin_object = models.Student.objects.filter(**form.cleaned_data).first()
        if not admin_object:
            form.add_error('password', '用户名或密码错误')
            return render(request, 'login/login.html', {'form': form})

        # 用户名和密码正确
        # 网站生成水机字符串，写到用户浏览器的Cookie中，再写入到Session中
        request.session['info'] = {
            'id': admin_object.id,
            'name': admin_object.name,
            'type': 'student',
        }
        # 重置session超时时间，即下次登录时间为：七天后
        request.session.set_expiry(60 * 60 * 24)

        return redirect('/student/users/profile/')

    data = {
        'form': StudentLoginForm(),
        'name_ch': '学生',
    }

    return render(request, 'login/login.html', data)


#############################################################


def logout_account(request):
    """ 注销 """

    # 把当前用户的 session 清除
    request.session.clear()

    return redirect('/login/')
