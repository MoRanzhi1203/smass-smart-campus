"""S10 app 配置。"""
from django.apps import AppConfig


class SmassStepupConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_stepup'
    verbose_name = '再认证与双人审批'
