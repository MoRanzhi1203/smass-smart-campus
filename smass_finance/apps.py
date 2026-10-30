"""R18 app 配置。"""
from django.apps import AppConfig


class SmassFinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_finance'
    verbose_name = '学费与财务'
