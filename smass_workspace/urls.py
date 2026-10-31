"""SMASS 产品 URL：统一登录 + 三个角色工作台 + 复用的业务功能页。"""
from django.urls import include, path

from .views import auth, common

app_name = 'workspace'

urlpatterns = [
    path('', auth.root_view, name='root'),
    path('login/', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('no-role/', common.no_role, name='no_role'),
    path('profile/', common.profile, name='profile'),
    path('notifications/', common.notifications, name='notifications'),
    path('notifications/<int:pk>/read/', common.notification_read,
         name='notification_read'),
    path('notifications/read-all/', common.notifications_read_all,
         name='notifications_read_all'),

    path('student/', include('smass_workspace.urls_student')),
    path('teacher/', include('smass_workspace.urls_teacher')),
    path('admin/', include('smass_workspace.urls_admin')),
]
