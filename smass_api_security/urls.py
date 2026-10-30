"""S15 路由（挂在 ``/s15/`` 下）。"""
from django.urls import path

from . import views

app_name = 's15'

urlpatterns = [
    # 示例 API 端点
    path('api/v1/ping', views.ping, name='api_ping'),
    path('api/v1/students/count', views.students_count, name='api_students_count'),

    # 管理页面
    path('', views.admin, name='admin'),
    path('clients/new/', views.client_create, name='client_create'),
    path('tokens/new/', views.token_create, name='token_create'),
    path('tokens/<int:pk>/revoke/', views.token_revoke, name='token_revoke'),
]
