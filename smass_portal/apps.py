"""R20 app 配置。"""
from django.apps import AppConfig


class SmassPortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_portal'
    verbose_name = '统一门户'
