"""R18 路由（挂在 ``/r18/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r18'

urlpatterns = [
    path('bills/', views.bill_list, name='bills'),
    path('bills/create/', views.bill_create, name='bill_create'),
    path('bills/<int:pk>/', views.bill_detail, name='bill_detail'),
    path('bills/<int:pk>/pay/', views.bill_pay, name='bill_pay'),
    path('bills/<int:pk>/refund/', views.refund_request, name='refund_request'),

    path('fee-items/create/', views.fee_item_create, name='fee_item_create'),

    path('refunds/', views.refund_list, name='refunds'),
    path('refunds/<int:pk>/<str:action>/', views.refund_action, name='refund_action'),

    path('ledger/', views.ledger_list, name='ledger'),
]
