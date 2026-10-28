"""R2.2 隔离 URL（只含认证、身份探针与审计探针）。"""
from django.urls import path

from r21_account import views as r21_views
from r22_account import views as r22_views

urlpatterns = [
    # 复用 R2.1 的统一认证与改密
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', r21_views.home_view, name='r21_home'),
    path('r21/change-password/', r21_views.change_password_view, name='r21_change_password'),
    path('r21/ping/', r21_views.ping_view, name='r21_ping'),

    # R2.2 身份与审计探针
    # ``/identity/`` 故意不带策略前缀：匿名也能访问，用于诊断身份解析
    path('identity/', r22_views.identity_view, name='r22_identity'),
    path('r22/audit/probe/', r22_views.audit_probe_view, name='r22_audit_probe'),
    path('r22/audit/fail/', r22_views.audit_fail_probe_view, name='r22_audit_fail'),
    path('legacy-parity/', r22_views.legacy_parity_view, name='legacy_parity'),
]
