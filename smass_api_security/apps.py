"""S15 app 配置。"""
from django.apps import AppConfig


class SmassApiSecurityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_api_security'
    verbose_name = 'API 安全'
