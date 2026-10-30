"""S18 组合 URLConf：统一登录 + 全部业务模块页面（跨模块负向测试）。"""
from django.urls import include, path

from r21_account import views as r21_views

urlpatterns = [
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', r21_views.home_view, name='r21_home'),

    path('r12/', include('smass_enrollment.urls')),
    path('r13/', include('smass_attendance.urls')),
    path('r14/', include('smass_activities.urls')),
    path('r15/', include('smass_clubs.urls')),
    path('r17/', include('smass_forum.urls')),
    path('r18/', include('smass_finance.urls')),
    path('r19/', include('smass_party.urls')),
    path('uploads/', include('smass_uploads.urls')),
    path('s16/', include('smass_audit.urls')),
]
