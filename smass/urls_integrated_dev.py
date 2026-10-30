"""集成开发 URLConf：统一入口 + R10 管理 + R11–R20 业务。

设计要点
--------
1. ``/`` 跳 ``/hub/``，``/hub/`` 是按角色展示模块入口的统一首页；
2. ``/r21/home/`` 在本配置中指向 hub（覆盖 R10 的 ``/r10/`` 跳转），
   但 **R10 独立配置**（``smass.settings_r10``）不受影响；
3. R10 的完整路由（r4–r9、r21 登录/改密）直接复用 ``urls_r10``；
4. R11 的路由在 ``urls_r11`` 内联定义，这里过滤掉其登录/登出后合并；
5. R16–R20 用 ``include`` 挂到各自前缀，命名空间互不重叠（r12–r20）；
6. 每个 URL 名在本文件内唯一（不与 ``urls_r10`` 的 ``r21_login`` 等重名）。
"""
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView

from smass_operations import views as ops_views

from . import urls_r11
from .dev_hub import hub
from .urls_r10 import urlpatterns as _r10_patterns

#: 这些名字属于"入口/认证"，集成配置里由 hub 统一提供，避免路径与命名冲突
_ENTRY_NAMES = {
    'r11_login', 'r11_logout', 'r16_login', 'r16_logout',
    'r21_login', 'r21_logout', 'r21_home', 'r11_home', 'r16_home',
}


def _business_patterns(patterns):
    return [item for item in patterns
            if getattr(item, 'name', None) not in _ENTRY_NAMES]


#: 本配置自带入口（必须排在 _r10_patterns 之前，先匹配先生效）
_ENTRY_PATTERNS = [
    path('', RedirectView.as_view(url='/hub/', permanent=False),
         name='integrated_root'),
    path('hub/', hub, name='integrated_hub'),
    # 登录后的落地页：统一跳 hub（r21 登录视图固定跳 /r21/home/）
    path('r21/home/', RedirectView.as_view(url='/hub/', permanent=False),
         name='integrated_home'),
    # R10 首页在独立配置中允许匿名浏览；集成入口要求先登录（统一登录）
    path('r10/', login_required(ops_views.nav_home), name='integrated_r10_home'),
]

#: R11–R20（R11 直接合并其业务路由，其余 include）
_MODULE_PATTERNS = [
    *_business_patterns(urls_r11.urlpatterns),
    path('r12/', include('smass_enrollment.urls')),
    path('r13/', include('smass_attendance.urls')),
    path('r14/', include('smass_activities.urls')),
    path('r15/', include('smass_clubs.urls')),
    # R16 的门户路由（/r16/rooms 等）来自 smass_facilities
    path('r16/', include('smass_facilities.urls')),
    path('r17/', include('smass_forum.urls')),
    path('r18/', include('smass_finance.urls')),
    path('r19/', include('smass_party.urls')),
    path('r20/', include('smass_portal.urls')),
]

urlpatterns = _ENTRY_PATTERNS + _r10_patterns + _MODULE_PATTERNS
