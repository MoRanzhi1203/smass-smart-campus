"""S10 路由（挂在 ``/s10/`` 下）。"""
from django.urls import path

from . import views

app_name = 's10'

urlpatterns = [
    path('', views.index, name='index'),
    path('verify/', views.verify_page, name='verify'),
    path('verify/submit/', views.verify_submit, name='verify_submit'),
    path('approvals/', views.approval_list, name='approvals'),
    path('approvals/new/', views.approval_open, name='approval_open'),
    path('approvals/<int:pk>/<str:action>/', views.approval_action, name='approval_action'),
]
