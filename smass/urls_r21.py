"""R2.1 原型 URL（只含统一认证与改密相关路径）。"""
from django.urls import path

from r21_account import views

urlpatterns = [
    path('r21/login/', views.login_view, name='r21_login'),
    path('r21/logout/', views.logout_view, name='r21_logout'),
    path('r21/home/', views.home_view, name='r21_home'),
    path('r21/change-password/', views.change_password_view, name='r21_change_password'),
    # 一个受保护的最小后台，用于验证 RBAC 与强制改密
    path('r21/ping/', views.ping_view, name='r21_ping'),
]
