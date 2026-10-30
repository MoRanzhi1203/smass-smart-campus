"""S16 路由（挂在 ``/s16/`` 下）。"""
from django.urls import path

from . import views

app_name = 's16'

urlpatterns = [
    path('events/', views.event_list, name='events'),
    path('alerts/', views.alert_list, name='alerts'),
    path('alerts/scan/', views.alert_scan, name='alert_scan'),
    path('alerts/<int:pk>/ack/', views.alert_ack, name='alert_ack'),
]
