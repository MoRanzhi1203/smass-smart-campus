"""S14 app 配置。"""
from django.apps import AppConfig


class SmassUploadsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_uploads'
    verbose_name = '安全文件上传'
