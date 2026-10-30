"""R19 路由（挂在 ``/r19/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r19'

urlpatterns = [
    path('orgs/', views.org_list, name='orgs'),
    path('orgs/create/', views.org_create, name='org_create'),
    path('orgs/<int:pk>/', views.org_detail, name='org_detail'),
    path('orgs/<int:pk>/members/add/', views.member_add, name='member_add'),
    path('orgs/<int:pk>/activities/add/', views.activity_create, name='activity_create'),
    path('activities/<int:pk>/complete/', views.activity_complete, name='activity_complete'),
    path('orgs/<int:pk>/documents/add/', views.document_create, name='document_create'),

    path('documents/<int:pk>/', views.document_detail, name='document_detail'),
    path('documents/<int:pk>/request/', views.document_request, name='document_request'),

    path('access/', views.access_list, name='access'),
    path('access/<int:pk>/<str:action>/', views.access_action, name='access_action'),

    path('audit/', views.audit_list, name='audit'),
]
