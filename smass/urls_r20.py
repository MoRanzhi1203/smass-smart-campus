"""R20 隔离 URL：统一登录 + 门户。"""
from django.urls import include, path

from r21_account import views as r21_views

urlpatterns = [
    path('r20/login/', r21_views.login_view, name='r20_login'),
    path('r20/logout/', r21_views.logout_view, name='r20_logout'),

    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', r21_views.home_view, name='r21_home'),

    path('r20/', include('smass_portal.urls')),
]
