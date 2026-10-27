"""敏感响应禁止缓存中间件。

背景（R1.5-B.7）：重置密码接口会把一次性口令放进 JSON，批量导入结果页会把
"本次导入账号的统一初始口令"渲染进 HTML。若被浏览器/代理缓存，口令可能残留于
磁盘缓存、后退历史或共享代理中。

策略：对路径匹配 ``/resetPass/`` 或 ``/multi/`` 的响应统一加
``Cache-Control: no-store, no-cache, must-revalidate, private, max-age=0``，
并附带 ``Pragma: no-cache`` 兼容旧代理。
"""
import re

from django.utils.deprecation import MiddlewareMixin

#: 需要禁止缓存的路径模式（命中任一即生效）
SENSITIVE_PATH_PATTERNS = (
    re.compile(r'/resetPass/?$', re.IGNORECASE),
    re.compile(r'/multi/?$', re.IGNORECASE),
    re.compile(r'/obtain/?$', re.IGNORECASE),
)

NO_STORE_VALUE = 'no-store, no-cache, must-revalidate, private, max-age=0'


class SensitiveResponseMiddleware(MiddlewareMixin):
    """给含一次性口令等敏感内容的响应加上禁止缓存头。"""

    @staticmethod
    def is_sensitive_path(path):
        return any(pattern.search(path or '') for pattern in SENSITIVE_PATH_PATTERNS)

    def process_response(self, request, response):
        if self.is_sensitive_path(getattr(request, 'path', '')):
            response['Cache-Control'] = NO_STORE_VALUE
            response['Pragma'] = 'no-cache'
            # 避免被搜索引擎或中间缓存收录
            response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response
