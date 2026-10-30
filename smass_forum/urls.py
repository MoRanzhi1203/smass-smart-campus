"""R17 路由（挂在 ``/r17/`` 下）。"""
from django.urls import path

from . import views

app_name = 'r17'

urlpatterns = [
    path('forum/', views.forum_index, name='forum'),
    path('forum/board/<int:pk>/', views.board_detail, name='board'),
    path('forum/board/<int:pk>/post/', views.post_create, name='post_create'),
    path('forum/post/<int:pk>/', views.post_detail, name='post'),
    path('forum/post/<int:pk>/comment/', views.comment_create, name='comment_create'),
    path('forum/post/<int:pk>/action/', views.content_action, name='content_action'),
    path('forum/report/', views.content_report, name='content_report'),

    path('reports/', views.report_list, name='reports'),
    path('reports/<int:pk>/resolve/', views.report_resolve, name='report_resolve'),

    path('announcements/', views.announcement_list, name='announcements'),
    path('announcements/create/', views.announcement_create,
         name='announcement_create'),
    path('announcements/<int:pk>/publish/', views.announcement_publish,
         name='announcement_publish'),
]
