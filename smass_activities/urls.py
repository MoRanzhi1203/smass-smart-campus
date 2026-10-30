"""R14 路由（挂在 ``/r14/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r14'

urlpatterns = [
    path('activities/', views.activity_list, name='activities'),
    path('activities/create/', views.activity_create, name='activity_create'),
    path('activities/<int:pk>/', views.activity_detail, name='activity_detail'),
    path('activities/<int:pk>/publish/', views.activity_publish, name='activity_publish'),
    path('activities/<int:pk>/close/', views.activity_close, name='activity_close'),
    path('activities/<int:pk>/generate-credits/', views.activity_generate_credits,
         name='activity_generate_credits'),
    path('activities/<int:pk>/register/', views.activity_register, name='activity_register'),

    path('registrations/<int:pk>/cancel/', views.registration_cancel,
         name='registration_cancel'),
    path('registrations/<int:pk>/checkin/', views.activity_check_in,
         name='activity_check_in'),

    path('credits/', views.credit_list, name='credits'),
    path('credits/<int:pk>/<str:action>/', views.credit_action, name='credit_action'),
]
