"""学生端路由。"""
from django.urls import path

from app01.views.student import st_classes_list, st_users_profile

urlpatterns = [
    # 个人主页
    path('student/users/profile/', st_users_profile.student_users_profile, name='student_profile'),
    # 修改本人密码
    path('student/users/change/password/', st_users_profile.student_change_password, name='student_change_password'),
    # 本班同学列表
    path('student/classes/list/', st_classes_list.classes_list, name='student_classes_list'),
]
