"""空 URL 配置（仅供路径 B 的全新基线实验使用）。

路径 B 实验刻意不加载 ``app01``，但原始 ``smass/urls.py`` 会间接 import
``app01.views`` → ``app01.models``，从而报
"Model class ... isn't in an application in INSTALLED_APPS"。
这本身就是 A/B 对比的一条实测证据：**切换 AUTH_USER_MODEL 需要连带处理
urlconf、中间件对旧 app 的依赖**。
"""
urlpatterns = []
