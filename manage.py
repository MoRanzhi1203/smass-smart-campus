#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks.

    默认进入 **V2.2 统一校园业务库**（``smass_campus``，唯一长期业务库）。
    历史系统、隔离演练与仿真配置必须显式指定，例如：

        python manage.py runserver --settings=smass.settings_simulation
        python manage.py test app01 --settings=smass.settings

    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_campus')
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
