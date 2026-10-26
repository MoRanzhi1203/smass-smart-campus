"""教师端路由。"""
from django.urls import path

from app01.views.teacher import te_basic

urlpatterns = [
    path('teacher/basic/', te_basic.teacher_basic, name='teacher_basic'),
]
