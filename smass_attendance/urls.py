"""R13 路由（挂在 ``/r13/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r13'

urlpatterns = [
    path('sessions/', views.session_list, name='sessions'),
    path('sessions/create/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
    path('sessions/<int:pk>/sign/', views.session_sign, name='session_sign'),
    path('sessions/<int:pk>/close/', views.session_close, name='session_close'),
    path('sessions/<int:pk>/mark/', views.session_mark, name='session_mark'),

    path('leaves/', views.leave_list, name='leaves'),
    path('leaves/submit/', views.leave_submit, name='leave_submit'),
    path('leaves/<int:pk>/<str:action>/', views.leave_action, name='leave_action'),

    path('makeups/', views.makeup_list, name='makeups'),
    path('makeups/submit/', views.makeup_submit, name='makeup_submit'),
    path('makeups/<int:pk>/<str:action>/', views.makeup_action, name='makeup_action'),

    path('stats/', views.stats_view, name='stats'),
]
