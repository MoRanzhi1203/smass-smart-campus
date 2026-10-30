"""R20 路由（挂在 ``/r20/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r20'

urlpatterns = [
    path('', views.portal_home, name='home'),
    path('admin/', views.portal_admin, name='admin'),
    path('admin/bootstrap/', views.admin_bootstrap, name='admin_bootstrap'),
    path('admin/section/', views.section_create, name='section_create'),
    path('admin/link/', views.link_create, name='link_create'),
    path('admin/notice/', views.notice_create, name='notice_create'),
    path('admin/notice/<int:pk>/publish/', views.notice_publish, name='notice_publish'),
]
