"""S18 app 配置（仅承载跨模块负向测试，无模型）。"""
from django.apps import AppConfig


class SmassSecurityTestsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_security_tests'
    verbose_name = '跨模块安全负向测试'
