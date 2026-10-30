"""R12 app 配置。"""
from django.apps import AppConfig


class SmassEnrollmentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_enrollment'
    verbose_name = '学籍管理与分班'
