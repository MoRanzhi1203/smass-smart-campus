"""SMASS URL 总入口。

按业务域拆分为独立子模块，全部使用命名路由（``reverse()`` / ``{% url %}``）。
历史版本把"接口地址"交给模板里的 ``str_dict.name_en`` 拼装，导致
班委后台的 AJAX 实际打到团学干部接口；命名路由可以从根上避免这类串台。

⚠️ 外部已发布路径保持不变，不破坏既有书签与前端调用。
"""
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    # 媒体文件（开发环境专用；生产应由 Nginx 等前置服务器托管）
    re_path(
        r'^media/(?P<path>.*)$',
        serve,
        {'document_root': settings.MEDIA_ROOT},
        name='media',
    ),

    # 账号与登录
    path('', include('smass.urls_account')),
    # 管理员后台
    path('', include('smass.urls_admin')),
    # 学生端
    path('', include('smass.urls_student')),
    # 教师端
    path('', include('smass.urls_teacher')),
]
