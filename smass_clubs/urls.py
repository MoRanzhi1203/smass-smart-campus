"""R15 路由（挂在 ``/r15/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r15'

urlpatterns = [
    path('clubs/', views.club_list, name='clubs'),
    path('clubs/create/', views.club_create, name='club_create'),
    path('clubs/<int:pk>/', views.club_detail, name='club_detail'),
    path('clubs/<int:pk>/apply/', views.club_apply, name='club_apply'),
    path('clubs/<int:pk>/appoint/', views.post_appoint, name='post_appoint'),

    path('memberships/<int:pk>/<str:action>/', views.membership_action,
         name='membership_action'),
    path('posts/', views.post_list, name='posts'),
    path('posts/<int:pk>/end/', views.post_end, name='post_end'),
]
