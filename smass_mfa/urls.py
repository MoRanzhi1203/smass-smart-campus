"""S09 路由（挂在 ``/s09/`` 下）。"""
from django.urls import path

from . import views

app_name = 's09'

urlpatterns = [
    path('setup/', views.setup, name='setup'),
    path('verify/', views.verify, name='verify'),
    path('status/', views.status, name='status'),
    path('disable/', views.disable, name='disable'),
    path('recovery/regenerate/', views.regenerate, name='regenerate'),
]
