"""数据库与迁移状态只读检查。

用途：在没有 `manage.py dbshell` 或需要结构化输出的场合，快速确认
"连的是哪个库、有几张表、字符集是什么、各表行数"。

安全：**不输出密码**，只输出"是否已配置密码"的布尔值。

用法：
    python scripts/db_inspect.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings')

import django  # noqa: E402  (必须在设置环境变量之后导入)

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402


def main():
    settings_dict = connection.settings_dict
    print('engine      :', settings_dict['ENGINE'])
    print('database    :', settings_dict['NAME'])
    print('host / port :', settings_dict['HOST'], '/', settings_dict['PORT'])
    print('pwd_set     :', bool(settings_dict['PASSWORD']))

    with connection.cursor() as cur:
        cur.execute('SELECT VERSION()')
        print('mysql       :', cur.fetchone()[0])

        cur.execute(
            'SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME '
            'FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()'
        )
        print('db charset  :', cur.fetchone())

        cur.execute(
            'SELECT COUNT(TABLE_NAME) FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA = DATABASE()'
        )
        print('table count :', cur.fetchone()[0])

        cur.execute(
            'SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME'
        )
        print('--- tables ---')
        for name, collation in cur.fetchall():
            print('  {:<32} {}'.format(name, collation))

        cur.execute(
            'SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 5'
        )
        print('--- last migrations ---')
        for app, name in cur.fetchall():
            print('  {:<12} {}'.format(app, name))

    print('--- app01 row counts ---')
    for model in apps.get_app_config('app01').get_models():
        print('  {:<18} {}'.format(model.__name__, model.objects.count()))


if __name__ == '__main__':
    main()
