"""G1-B 探测：已有 auth_user 数据的库，切换到自定义 AUTH_USER_MODEL 后会发生什么。

只读 + 最小写入（在 ``smass_r22_*`` 隔离库内）：
1. 打印当前 AUTH_USER_MODEL；
2. 查 ``django_admin_log.user_id`` 的**实际外键指向**（information_schema）；
3. 用自定义用户写一条 LogEntry，观察 FK 行为；
4. 确认 ``auth_user`` 表与数据仍在（切换不会自动迁移旧数据）。

用法：
    $env:R22B_DB = 'smass_r22_b_switch'
    conda run -n smass python scripts/r22_b_switch_probe.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r22_b')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.admin.models import ADDITION, LogEntry  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.db import IntegrityError, connection, transaction  # noqa: E402


def guard():
    db = connection.settings_dict['NAME'] or ''
    if not db.startswith('smass_r22_'):
        raise SystemExit('拒绝：只在 smass_r22_* 实验库执行，当前 {!r}'.format(db))
    print('target database : {}'.format(db))


def main():
    guard()

    print('AUTH_USER_MODEL : {}'.format(settings.AUTH_USER_MODEL))
    print('get_user_model(): {}'.format(get_user_model()._meta.label_lower))

    user_model = get_user_model()

    with connection.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN "
            "('auth_user', 'django_admin_log', 'proto_user_model_protouser')",
            [connection.settings_dict['NAME']],
        )
        tables = sorted(row[0] for row in cur.fetchall())
        print('tables present  : {}'.format(tables))

        cur.execute(
            "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'django_admin_log' "
            "AND REFERENCED_TABLE_NAME IS NOT NULL",
            [connection.settings_dict['NAME']],
        )
        fks = cur.fetchall()
        print('admin_log FKs   : {}'.format(fks))

    # ---- 用自定义用户写 LogEntry ----
    account, created = user_model.objects.get_or_create(
        login_name='B_SWITCH_PROBE',
        defaults={'display_name': '切换探测', 'person_type': 'admin'},
    )
    if created:
        account.set_password('Probe#2024')
        account.must_change_password = False
        account.save()

    print('probe user pk   : {}'.format(account.pk))

    content_type = ContentType.objects.get_for_model(user_model)
    wrote = None
    error = None
    try:
        with transaction.atomic():
            LogEntry.objects.log_action(
                user_id=account.pk,
                content_type_id=content_type.pk,
                object_id='1',
                object_repr='switch probe',
                action_flag=ADDITION,
                change_message='probe',
            )
        wrote = True
    except IntegrityError as exc:
        wrote = False
        error = exc

    print('log_entry wrote : {} (error={})'.format(
        wrote, type(error).__name__ if error else None
    ))

    # ---- 旧数据是否还在 ----
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM auth_user')
        legacy_users = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM {}'.format(user_model._meta.db_table))
        new_users = cur.fetchone()[0]

    print('auth_user rows  : {}'.format(legacy_users))
    print('new user rows   : {}'.format(new_users))

    print('')
    print('SUMMARY: switching AUTH_USER_MODEL on an existing DB does NOT migrate auth_user;'
          ' admin log FK and legacy identities remain on the old table.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
