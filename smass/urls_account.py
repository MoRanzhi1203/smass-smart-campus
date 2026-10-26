"""账号与登录路由。

注意：本项目**不使用** Django 原生 admin 站点，``/admin/`` 前缀属于业务后台。
"""
from django.urls import path

from app01.views import account

urlpatterns = [
    # 登录主页面（角色选择）
    path('login/', account.login, name='login'),
    # 管理员登录
    path('login/account/admin/', account.login_admin, name='login_admin'),
    # 学生登录
    path('login/account/student/', account.login_student, name='login_student'),
    # 教师登录（历史版本被注释掉，导致教师端免登录可进入）
    path('login/account/teacher/', account.login_teacher, name='login_teacher'),
    # 注销
    path('logout/', account.logout_account, name='logout'),
]
