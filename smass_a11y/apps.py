"""S19 app 配置（纯工具 + 报告页，无模型）。"""
from django.apps import AppConfig


class SmassA11yConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_a11y'
    verbose_name = '可访问性'
