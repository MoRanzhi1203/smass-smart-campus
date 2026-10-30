"""S13 app 配置。"""
from django.apps import AppConfig


class SmassPrivacyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_privacy'
    verbose_name = '数据最小化与披露控制'
