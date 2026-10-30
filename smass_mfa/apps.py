"""S09 app 配置。"""
from django.apps import AppConfig


class SmassMfaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_mfa'
    verbose_name = '多因素认证'
