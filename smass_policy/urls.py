"""S11 路由（挂在 ``/s11/`` 下）。"""
from django.urls import path

from . import views

app_name = 's11'

urlpatterns = [
    path('policies/', views.policy_list, name='policies'),
    path('policies/save/', views.policy_save, name='policy_save'),
    path('policies/<int:pk>/disable/', views.policy_disable, name='policy_disable'),
    path('preview/', views.preview, name='preview'),
]
