#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks.

    默认进入**产品配置**（三端 + 统一账号），避免误用旧版 app01 系统。
    历史系统与各 R 系列隔离配置必须显式指定，例如：

        python manage.py test app01 --settings=smass.settings
        python manage.py runserver --settings=smass.settings_r11
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_product')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
