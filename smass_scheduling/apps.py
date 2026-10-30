"""R11 app 配置。"""
from django.apps import AppConfig


class SmassSchedulingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_scheduling'
    verbose_name = '排课与课表'
