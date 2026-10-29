"""R10 隔离 URL：统一外壳 + 各模块路由汇合。"""
from django.urls import path
from django.views.generic import RedirectView

from r21_account import views as r21_views
from smass_operations import ui_views, views as ops_views

from smass.urls_r4 import urlpatterns as r4_patterns
from smass.urls_r5 import urlpatterns as r5_patterns
from smass.urls_r6 import urlpatterns as r6_patterns
from smass.urls_r7 import urlpatterns as r7_patterns
from smass.urls_r8 import urlpatterns as r8_patterns
from smass.urls_r9 import urlpatterns as r9_patterns

urlpatterns = [
    path('r10/', ops_views.nav_home, name='r10_home'),

    # 统一身份入口
    path('r21/login/', r21_views.login_view, name='r21_login'),
    path('r21/logout/', r21_views.logout_view, name='r21_logout'),
    path('r21/home/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_home'),
    path('r21/change-password/', RedirectView.as_view(url='/r10/', permanent=False),
         name='r21_change_password_redirect'),

    # R10 UI 新增页（U3 导入 / U7 API 文档与运维）
    path('r4/import/', ui_views.import_page, name='r4_import_page'),
    path('r4/import/preview/', ui_views.import_preview, name='r4_import_preview_ui'),
    path('r8/docs/', ui_views.api_docs, name='r8_api_docs'),
    path('r9/status/', ui_views.ops_status, name='r9_ops_status'),
]

for patterns in (r4_patterns, r5_patterns, r6_patterns, r7_patterns,
                 r8_patterns, r9_patterns):
    urlpatterns += patterns
