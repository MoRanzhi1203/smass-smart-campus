"""R7 隔离 URL：指标看板与报表。"""
from django.urls import path

from r21_account import views as r21_views
from smass_analytics import views

urlpatterns = [
    path('r7/login/', r21_views.login_view, name='r7_login'),
    path('r7/logout/', r21_views.logout_view, name='r7_logout'),
    path('r7/health/', views.health, name='r7_health'),
    path('r7/dashboard/', views.dashboard, name='r7_dashboard'),
    path('r7/metrics/', views.metric_list, name='r7_metric_list'),
    path('r7/reports/<str:code>/run/', views.report_run, name='r7_report_run'),
    path('r7/reports/<str:code>/export/', views.report_export, name='r7_report_export'),
]