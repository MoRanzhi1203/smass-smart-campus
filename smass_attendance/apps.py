"""R13 app 配置。"""
from django.apps import AppConfig


class SmassAttendanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_attendance'
    verbose_name = '考勤与请销假'
