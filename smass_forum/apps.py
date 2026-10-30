"""R17 app 配置。"""
from django.apps import AppConfig


class SmassForumConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_forum'
    verbose_name = '论坛与公告'
