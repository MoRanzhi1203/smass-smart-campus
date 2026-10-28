"""R9 请求指标中间件（仅隔离配置启用）。"""
import time

from smass_operations import services


class RequestMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        try:
            services.record_request(
                request, response.status_code, (time.perf_counter() - started) * 1000
            )
        except Exception:  # noqa: BLE001
            pass
        return response