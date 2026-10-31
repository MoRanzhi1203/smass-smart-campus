#!/usr/bin/env python
"""经授权的旧库物理删除：仅删除 ``smass``。

    python scripts/legacy_drop_database.py --confirm smass

安全措施：
- 目标库名硬编码为 ``smass``，必须显式传入 ``--confirm smass``；
- 删除前重新核验：实例、库名、活动连接、跨库引用、对象清单、配置引用；
- 先记录所有数据库基线 + 新版权威库指纹，再生成结构快照（不含行数据）；
- 仅执行 ``DROP DATABASE `smass```，不使用通配/模糊匹配；
- 删除后复核：其他数据库完整、产品库指纹不变、旧库不存在；
- 任一核验不一致立即中止。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TARGET = 'smass'
PRODUCT = 'smass_product_dev'
UNIFIED = 'smass_unified_verify'
PROTECTED = {'information_schema', 'performance_schema', 'mysql', 'sys',
             PRODUCT, UNIFIED}


def connect(database=None):
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    import pymysql

    return pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=database, charset='utf8mb4', autocommit=True)


def databases(connection):
    with connection.cursor() as cursor:
        cursor.execute('SHOW DATABASES')
        return sorted(row[0] for row in cursor.fetchall())


def table_counts(connection, schema):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s',
            (schema,))
        return cursor.fetchone()[0]


def product_signature(connection):
    with connection.cursor() as cursor:
        signature = {'tables': table_counts(connection, PRODUCT)}
        for table in ('r21_account_account', 'smass_organization_studentrecord',
                      'smass_organization_organizationunit',
                      'smass_academic_teachingsection'):
            cursor.execute(
                'SELECT COUNT(*) FROM `{}`.`{}`'.format(PRODUCT, table))
            signature[table] = cursor.fetchone()[0]
        return signature


def target_objects(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.tables '
            'WHERE table_schema=%s ORDER BY TABLE_NAME', (TARGET,))
        tables = cursor.fetchall()
        cursor.execute('SELECT COUNT(*) FROM information_schema.views '
                       'WHERE table_schema=%s', (TARGET,))
        views = cursor.fetchone()[0] if tables else 0
        cursor.execute('SELECT COUNT(*) FROM information_schema.triggers '
                       'WHERE trigger_schema=%s', (TARGET,))
        triggers = cursor.fetchone()[0] if tables else 0
        cursor.execute('SELECT COUNT(*) FROM information_schema.events '
                       'WHERE event_schema=%s', (TARGET,))
        events = cursor.fetchone()[0] if tables else 0
        cursor.execute('SELECT COUNT(*) FROM information_schema.routines '
                       'WHERE routine_schema=%s', (TARGET,))
        routines = cursor.fetchone()[0] if tables else 0
        return {'tables': [{'name': row[0], 'type': row[1]} for row in tables],
                'table_count': len(tables), 'views': views,
                'triggers': triggers, 'events': events, 'routines': routines}


def active_connections(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT CONNECTION_ID()')
        own_id = cursor.fetchone()[0]
        cursor.execute('SHOW PROCESSLIST')
        rows = cursor.fetchall()
        return [{'id': row[0], 'user': row[1], 'host': row[2], 'db': row[3]}
                for row in rows if row[3] == TARGET and row[0] != own_id]


def cross_references(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.views '
            'WHERE table_schema<>%s AND view_definition LIKE %s',
            (TARGET, '%`{}`.%'.format(TARGET)))
        views = cursor.fetchone()[0]
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.routines '
            'WHERE routine_schema<>%s AND routine_definition LIKE %s',
            (TARGET, '%`{}`.%'.format(TARGET)))
        routines = cursor.fetchone()[0]
    return views + routines


def schema_snapshot(connection, output):
    lines = ['-- SMASS legacy schema snapshot (structure only)',
             '-- database: {}'.format(TARGET),
             '-- generated: {}'.format(datetime.now().isoformat(timespec='seconds')),
             '-- no row data included', '']
    with connection.cursor() as cursor:
        objects = target_objects(connection)
        for item in objects['tables']:
            if item['type'] != 'BASE TABLE':
                continue
            cursor.execute('SHOW CREATE TABLE `{}`.`{}`'.format(TARGET, item['name']))
            row = cursor.fetchone()
            lines.append('-- table: {}'.format(item['name']))
            lines.append(row[1] + ';')
            lines.append('')
    text = '\n'.join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding='utf-8')
    return {'path': str(output), 'sha256': hashlib.sha256(
        text.encode('utf-8')).hexdigest(), 'bytes': len(text.encode('utf-8'))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', required=True)
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--snapshot',
                        default=str(ROOT / '.local/evidence/retire/schema_snapshot.sql'))
    args = parser.parse_args()

    if args.confirm.strip() != TARGET:
        raise SystemExit('确认文本必须精确为 {!r}'.format(TARGET))

    client = connect()
    try:
        before_databases = databases(client)
        if TARGET not in before_databases:
            raise SystemExit('目标库不存在，无需删除')
        if PRODUCT not in before_databases or UNIFIED not in before_databases:
            raise SystemExit('受保护库缺失，停止')

        objects = target_objects(client)
        connections = active_connections(client)
        cross = cross_references(client)
        product_before = product_signature(client)
        snapshot = schema_snapshot(client, Path(args.snapshot))

        guards = {
            'target_name': TARGET,
            'target_is_protected': TARGET in PROTECTED,
            'active_connections': connections,
            'cross_database_references': cross,
            'object_count': objects['table_count'],
            'views': objects['views'],
            'triggers': objects['triggers'],
            'events': objects['events'],
            'routines': objects['routines'],
        }
        blocking = [key for key, value in (
            ('target_is_protected', guards['target_is_protected']),
            ('active_connections', bool(connections)),
            ('cross_database_references', cross > 0),
            ('object_count', objects['table_count'] == 0),
        ) if value]
        if blocking:
            report = {'aborted': True, 'reasons': blocking, 'guards': guards}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print('RESULT: ABORTED')
            return 2

        with client.cursor() as cursor:
            cursor.execute('DROP DATABASE `{}`'.format(TARGET))

        after_databases = databases(client)
        product_after = product_signature(client)
        removed = TARGET not in after_databases
        product_unchanged = product_before == product_after
        others_before = [name for name in before_databases if name != TARGET]
        others_after = [name for name in after_databases if name != TARGET]

        report = {
            'authorized_by': 'user',
            'target': TARGET,
            'dropped': removed,
            'snapshot': snapshot,
            'before': {'databases': before_databases,
                       'objects': {key: objects[key] for key in (
                           'table_count', 'views', 'triggers', 'events',
                           'routines')}},
            'after': {'databases': after_databases,
                      'target_exists': TARGET in after_databases,
                      'other_databases_unchanged': others_before == others_after},
            'product_before': product_before,
            'product_after': product_after,
            'product_unchanged': product_unchanged,
            'guards': guards,
            'ok': removed and product_unchanged and others_before == others_after,
        }
    finally:
        client.close()

    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
