"""S19 路由（挂在 ``/s19/`` 下）。"""
from django.urls import path

from . import views

app_name = 's19'

urlpatterns = [
    path('', views.report, name='report'),
]
