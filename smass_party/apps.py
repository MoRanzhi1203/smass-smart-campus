"""R19 app 配置。"""
from django.apps import AppConfig


class SmassPartyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_party'
    verbose_name = '党建与专项组织'
