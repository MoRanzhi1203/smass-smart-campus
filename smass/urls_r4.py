"""R4 隔离 URL：组织与档案的最小可用页面/接口。"""
from django.urls import path

from smass_organization import views

urlpatterns = [
    path('r4/units/', views.unit_list, name='r4_unit_list'),
    path('r4/units/tree/', views.unit_tree, name='r4_unit_tree'),
    path('r4/units/create/', views.unit_create, name='r4_unit_create'),
    path('r4/units/<int:pk>/move/', views.unit_move, name='r4_unit_move'),
    path('r4/students/', views.student_list, name='r4_student_list'),
    path('r4/students/<str:student_no>/', views.student_detail, name='r4_student_detail'),
    path('r4/import/preview/', views.import_preview_view, name='r4_import_preview'),
    path('r4/import/commit/', views.import_commit_view, name='r4_import_commit'),
    path('r4/health/', views.health, name='r4_health'),
]
