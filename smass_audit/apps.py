"""S16 app 配置。"""
from django.apps import AppConfig


class SmassAuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_audit'
    verbose_name = '追加式审计'
