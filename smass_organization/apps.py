from django.apps import AppConfig


class SmassOrganizationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'smass_organization'
    verbose_name = 'SMASS R4 组织机构与学生档案'

    def ready(self):
        from . import signals  # noqa: F401 - 注册学籍→档案同步
