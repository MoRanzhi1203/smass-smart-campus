"""S13 路由（挂在 ``/s13/`` 下）。"""
from django.urls import path

from . import views

app_name = 's13'

urlpatterns = [
    path('fields/', views.field_list, name='fields'),
    path('fields/save/', views.field_save, name='field_save'),
    path('fields/purge/', views.field_purge, name='field_purge'),

    path('disclosures/', views.disclosure_list, name='disclosures'),
    path('disclosures/new/', views.disclosure_request, name='disclosure_request'),
    # 注意：export 必须放在 <action> 之前，否则会被当作 action='export'
    path('disclosures/<int:pk>/export/', views.disclosure_export,
         name='disclosure_export'),
    path('disclosures/<int:pk>/<str:action>/', views.disclosure_action,
         name='disclosure_action'),
]
