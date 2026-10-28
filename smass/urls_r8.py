"""R8 隔离 URL：版本化 API。"""
from django.urls import path

from r21_account import views as r21_views
from smass_api import views

urlpatterns = [
    path('r8/login/', r21_views.login_view, name='r8_login'),
    path('api/v1/openapi.json', views.openapi, name='api_openapi'),
    path('api/v1/units/', views.units, name='api_units'),
    path('api/v1/students/', views.students, name='api_students'),
    path('api/v1/sections/', views.sections, name='api_sections'),
    path('api/v1/workflow/instances/', views.instances, name='api_instances'),
    path('api/v1/sync/', views.sync, name='api_sync'),
]