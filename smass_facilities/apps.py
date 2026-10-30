"""R16 app 配置。"""
from django.apps import AppConfig


class SmassFacilitiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_facilities'
    verbose_name = '校园场地与设备'
