"""SMASS 产品 URLConf。

- 三端入口由 ``smass_workspace.urls`` 提供；
- R4–R9 与 R11–R20 的既有功能页按**业务路径**保留（``/r4/`` … ``/r20/``），
  但不再出现在主导航里，也不作为产品首页；
- ``/r10/`` 与 ``/hub/`` 只做重定向，避免出现"研发外壳"；
- ``/r21/login/`` 等历史入口 302 到统一登录，保证旧书签不失效。
"""
from django.urls import include, path
from django.views.generic import RedirectView

from . import urls_r11
from .urls_r10 import urlpatterns as _r10_patterns

#: 认证/入口类路由：产品里由统一登录接管，这里过滤掉
_ENTRY_NAMES = {
    'r10_home', 'r21_login', 'r21_logout', 'r21_home',
    'r11_login', 'r11_logout', 'r11_home',
}

#: 由产品自己提供的入口（必须排在旧路由之前）
_ENTRY_PATTERNS = [
    path('', include('smass_workspace.urls')),
    # 研发期入口统一收敛到产品首页
    path('hub/', RedirectView.as_view(url='/', permanent=False),
         name='legacy_hub'),
    path('r10/', RedirectView.as_view(url='/admin/', permanent=False),
         name='legacy_r10'),
    path('r21/login/', RedirectView.as_view(url='/login/', permanent=False),
         name='legacy_login'),
    path('r21/logout/', RedirectView.as_view(url='/logout/', permanent=False),
         name='legacy_logout'),
    path('r21/home/', RedirectView.as_view(url='/', permanent=False),
         name='legacy_home'),
    path('r11/login/', RedirectView.as_view(url='/login/', permanent=False),
         name='legacy_r11_login'),
    path('r11/logout/', RedirectView.as_view(url='/logout/', permanent=False),
         name='legacy_r11_logout'),
]


def _business_patterns(patterns):
    return [item for item in patterns
            if getattr(item, 'name', None) not in _ENTRY_NAMES]


#: R11–R20 深层功能页（保留既有 URL，供统一导航跳转）
_MODULE_PATTERNS = [
    *_business_patterns(urls_r11.urlpatterns),
    path('r12/', include('smass_enrollment.urls')),
    path('r13/', include('smass_attendance.urls')),
    path('r14/', include('smass_activities.urls')),
    path('r15/', include('smass_clubs.urls')),
    path('r16/', include('smass_facilities.urls')),
    path('r17/', include('smass_forum.urls')),
    path('r18/', include('smass_finance.urls')),
    path('r19/', include('smass_party.urls')),
    path('r20/', include('smass_portal.urls')),
]

urlpatterns = (
    _ENTRY_PATTERNS
    + _business_patterns(_r10_patterns)
    + _MODULE_PATTERNS
)
