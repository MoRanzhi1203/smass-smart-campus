"""R6 隔离 URL：工作流定义/实例/待办/消息。"""
from django.urls import path

from r21_account import views as r21_views
from smass_workflow import views

urlpatterns = [
    path('r6/login/', r21_views.login_view, name='r6_login'),
    path('r6/logout/', r21_views.logout_view, name='r6_logout'),
    path('r6/health/', views.health, name='r6_health'),
    path('r6/definitions/', views.definition_list, name='r6_definition_list'),
    path('r6/definitions/create/', views.definition_create, name='r6_definition_create'),
    path('r6/instances/', views.instance_list, name='r6_instance_list'),
    path('r6/instances/create/', views.instance_create, name='r6_instance_create'),
    path('r6/instances/<int:pk>/action/', views.instance_action, name='r6_instance_action'),
    path('r6/tasks/', views.task_list, name='r6_task_list'),
    path('r6/notifications/', views.notification_list, name='r6_notification_list'),
]