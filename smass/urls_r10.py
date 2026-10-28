"""R10 隔离 URL：统一导航 + 各模块路由汇合（发行候选视图）。"""
from django.urls import path

from smass_operations import views as ops_views

from smass.urls_r4 import urlpatterns as r4_patterns
from smass.urls_r5 import urlpatterns as r5_patterns
from smass.urls_r6 import urlpatterns as r6_patterns
from smass.urls_r7 import urlpatterns as r7_patterns
from smass.urls_r8 import urlpatterns as r8_patterns
from smass.urls_r9 import urlpatterns as r9_patterns

urlpatterns = [
    path('r10/', ops_views.nav_home, name='r10_home'),
]

# 汇合各模块路由（重复的登录路径由 Django 按先注册者匹配，功能不受影响）
for patterns in (r4_patterns, r5_patterns, r6_patterns, r7_patterns,
                 r8_patterns, r9_patterns):
    urlpatterns += patterns