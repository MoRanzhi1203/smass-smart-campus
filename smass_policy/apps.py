"""S11 app 配置。"""
from django.apps import AppConfig


class SmassPolicyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_policy'
    verbose_name = '字段级策略授权'
