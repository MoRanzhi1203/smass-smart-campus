"""SMASS 产品 URL：统一登录 + 三个角色工作台 + 复用的业务功能页。"""
from django.urls import include, path

from .views import auth, common, dormitory as dorm_views

app_name = 'workspace'

urlpatterns = [
    path('', auth.root_view, name='root'),
    path('login/', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('no-role/', common.no_role, name='no_role'),
    path('profile/', common.profile, name='profile'),
    path('notifications/', common.notifications, name='notifications'),
    path('dormitory/', dorm_views.home, name='dormitory_home'),
    path('dormitory/rooms/', dorm_views.rooms, name='dormitory_rooms'),
    path('dormitory/changes/<int:pk>/<str:action>/', dorm_views.change_action,
         name='dormitory_change_action'),
    path('dormitory/checkouts/<int:pk>/<str:action>/',
         dorm_views.checkout_action, name='dormitory_checkout_action'),
    path('dormitory/repairs/<int:pk>/advance/', dorm_views.repair_action,
         name='dormitory_repair_action'),
    path('dormitory/inspections/<int:pk>/advance/',
         dorm_views.inspection_action, name='dormitory_inspection_action'),
    path('notifications/<int:pk>/read/', common.notification_read,
         name='notification_read'),
    path('notifications/read-all/', common.notifications_read_all,
         name='notifications_read_all'),

    path('student/', include('smass_workspace.urls_student')),
    path('teacher/', include('smass_workspace.urls_teacher')),
    path('admin/', include('smass_workspace.urls_admin')),
]
