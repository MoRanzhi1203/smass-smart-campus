"""S14 路由（挂在 ``/uploads/`` 下）。"""
from django.urls import path

from . import views

app_name = 's14'

urlpatterns = [
    path('', views.file_list, name='files'),
    path('upload/', views.file_upload, name='upload'),
    path('<int:pk>/download/', views.file_download, name='download'),
    path('<int:pk>/delete/', views.file_delete, name='delete'),
]
