"""账号与登录路由。

注意：本项目**不使用** Django 原生 admin 站点，``/admin/`` 前缀属于业务后台。
"""
from django.urls import path

from app01.views import account, password_lifecycle, session_devices

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

    # S02：强制改密（三端共用）与管理员发放一次性临时口令
    path('account/password/forced/', password_lifecycle.password_forced_change,
         name='password_forced_change'),
    path('admin/admin/temp-password/', password_lifecycle.admin_issue_temp_password,
         name='admin_issue_temp_password'),

    # S17：并发登录设备与会话管理（三端共用，仅操作本人设备）
    path('account/sessions/', session_devices.session_list,
         name='account_sessions'),
    path('account/sessions/revoke-others/', session_devices.session_revoke_others,
         name='account_session_revoke_others'),
    path('account/sessions/revoke/<str:device_id>/', session_devices.session_revoke,
         name='account_session_revoke'),
]
