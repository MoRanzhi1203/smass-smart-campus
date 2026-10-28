"""R9 隔离 URL：健康检查与指标。"""
from django.urls import path

from smass_operations import views

urlpatterns = [
    path('r9/health/', views.health, name='r9_health'),
    path('r9/ready/', views.ready, name='r9_ready'),
    path('r9/metrics/', views.metrics, name='r9_metrics'),
    path('r9/alerts/', views.alerts, name='r9_alerts'),
]