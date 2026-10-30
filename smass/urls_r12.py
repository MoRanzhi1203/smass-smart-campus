"""R12 隔离 URL：统一登录 + 学籍管理页面。"""
from django.urls import include, path

from r21_account import views as r21_views

urlpatterns = [
    path('r12/login/', r21_views.login_view, name='r12_login'),
    path('r12/logout/', r21_views.logout_view, name='r12_logout'),

    # R21 登录模板的 form action 固定为 /r21/login/，浏览器流程需要该别名。
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', r21_views.home_view, name='r21_home'),

    path('r12/', include('smass_enrollment.urls')),
]
