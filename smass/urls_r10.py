"""R10 隔离 URL：统一导航 + 各模块路由汇合（发行候选视图）。"""
from django.urls import path
from django.views.generic import RedirectView

from r21_account import views as r21_views
from smass_operations import views as ops_views

from smass.urls_r4 import urlpatterns as r4_patterns
from smass.urls_r5 import urlpatterns as r5_patterns
from smass.urls_r6 import urlpatterns as r6_patterns
from smass.urls_r7 import urlpatterns as r7_patterns
from smass.urls_r8 import urlpatterns as r8_patterns
from smass.urls_r9 import urlpatterns as r9_patterns

urlpatterns = [
    path('r10/', ops_views.nav_home, name='r10_home'),

    # 统一登录入口（RoutePolicyMiddleware 拒绝时也跳这里）
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_home'),
    path('r21/change-password/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_change_password_redirect'),
]

for patterns in (r4_patterns, r5_patterns, r6_patterns, r7_patterns,
                 r8_patterns, r9_patterns):
    urlpatterns += patterns
