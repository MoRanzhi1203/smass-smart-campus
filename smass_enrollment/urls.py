"""R12 路由（挂在 ``/r12/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r12'

urlpatterns = [
    path('placement/', views.placement_list, name='placement_list'),
    path('placement/preview/<int:rule_id>/', views.placement_preview,
         name='placement_preview'),
    path('placement/<int:pk>/', views.placement_detail, name='placement_detail'),
    path('placement/<int:pk>/apply/', views.placement_apply, name='placement_apply'),
    path('placement/<int:pk>/rollback/', views.placement_rollback,
         name='placement_rollback'),

    path('transfers/', views.transfer_list, name='transfers'),
    path('transfers/submit/', views.transfer_submit, name='transfer_submit'),
    path('transfers/<int:pk>/<str:action>/', views.transfer_action,
         name='transfer_action'),

    path('status/', views.status_list, name='status'),
    path('status/submit/', views.status_submit, name='status_submit'),
    path('status/<int:pk>/<str:action>/', views.status_action, name='status_action'),
]
