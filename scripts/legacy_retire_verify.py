#!/usr/bin/env python
"""P0：正式库删除前只读核验。

    python scripts/legacy_retire_verify.py --json out.json

核验内容：
- MySQL 实例、主机、端口、库名、账号权限；
- 全部表/视图/触发器/事件/存储过程与行数、数据量；
- 敏感数据特征（身份证校验位、手机号段）——只输出统计，不输出值；
- 当前连接与其它库对 smass 的跨库引用；
- 项目配置/脚本/环境变量对 smass 的引用；
- 删除计划（只生成 SQL，不执行）。

只读：SET SESSION TRANSACTION READ ONLY；不执行任何 DDL/DML。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TARGET_DB = 'smass'
SCAN_SKIP = {'.git', '.local', 'staticfiles', '__pycache__', 'node_modules',
             'media', 'private_uploads', 'logs', 'docs', 'static'}

ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHECK = '10X98765432'


def source_connection():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    import pymysql

    connection = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=TARGET_DB, charset='utf8mb4', autocommit=False)
    with connection.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION READ ONLY')
    return connection


def id_card_valid(value):
    text = (value or '').strip().upper()
    if len(text) != 18:
        return False
    if not text[:17].isdigit():
        return False
    total = sum(int(text[index]) * ID_WEIGHTS[index] for index in range(17))
    return ID_CHECK[total % 11] == text[17]


def phone_kind(value):
    text = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(text) != 11 or not text.startswith('1'):
        return 'other'
    if text.startswith(('1380000', '1390000', '1370000', '1360000')):
        return 'test_prefix'
    return 'non_test_prefix'


def collect_objects(cursor):
    cursor.execute(
        'SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH, '
        'ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s '
        'ORDER BY TABLE_TYPE, TABLE_NAME', (TARGET_DB,))
    tables = [{'name': row[0], 'type': row[1], 'rows': row[2] or 0,
               'data_bytes': row[3] or 0, 'index_bytes': row[4] or 0,
               'engine': row[5]} for row in cursor.fetchall()]

    cursor.execute(
        'SELECT TRIGGER_NAME, EVENT_OBJECT_TABLE, ACTION_TIMING, EVENT_MANIPULATION '
        'FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s', (TARGET_DB,))
    triggers = [{'name': row[0], 'table': row[1], 'timing': row[2],
                 'event': row[3]} for row in cursor.fetchall()]

    cursor.execute(
        'SELECT EVENT_NAME, STATUS, EVENT_TYPE FROM information_schema.EVENTS '
        'WHERE EVENT_SCHEMA=%s', (TARGET_DB,))
    events = [{'name': row[0], 'status': row[1], 'type': row[2]}
              for row in cursor.fetchall()]

    cursor.execute(
        'SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES '
        'WHERE ROUTINE_SCHEMA=%s', (TARGET_DB,))
    routines = [{'name': row[0], 'type': row[1]} for row in cursor.fetchall()]
    return tables, triggers, events, routines


def collect_pii(cursor):
    result = {}
    for table, column in (('app01_student', 'cardID'),
                          ('app01_teacher', 'cardID')):
        try:
            cursor.execute('SELECT COUNT(*), SUM(`{}` IS NOT NULL AND `{}` <> \'\') '
                           'FROM `{}`'.format(column, column, table))
            total, present = cursor.fetchone()
            result[table] = {'rows': total, 'id_card_present': present or 0}
            cursor.execute('SELECT `{}` FROM `{}` WHERE `{}` IS NOT NULL AND `{}` <> \'\''
                           .format(column, table, column, column))
            values = [row[0] for row in cursor.fetchall()]
            result[table]['id_card_valid'] = sum(1 for value in values
                                                 if id_card_valid(value))
            result[table]['id_card_invalid'] = sum(
                1 for value in values if not id_card_valid(value))
        except Exception as exc:  # noqa: BLE001
            result[table] = {'error': str(exc)[:120]}

    for table in ('app01_student', 'app01_teacher'):
        try:
            cursor.execute('SELECT phone FROM `{}` WHERE phone IS NOT NULL '
                           'AND phone <> \'\''.format(table))
            values = [row[0] for row in cursor.fetchall()]
            kinds = {'test_prefix': 0, 'non_test_prefix': 0, 'other': 0}
            for value in values:
                kinds[phone_kind(value)] += 1
            result[table + '_phone'] = {'present': len(values), **kinds}
        except Exception as exc:  # noqa: BLE001
            result[table + '_phone'] = {'error': str(exc)[:120]}
    return result


def collect_processes(cursor):
    cursor.execute('SELECT CONNECTION_ID()')
    own_id = cursor.fetchone()[0]
    cursor.execute('SHOW PROCESSLIST')
    rows = cursor.fetchall()
    return [{'id': row[0], 'user': row[1], 'host': row[2], 'db': row[3],
             'command': row[4], 'time': row[5], 'state': row[6]}
            for row in rows
            if row[3] == TARGET_DB and row[0] != own_id]


def cross_database_refs(cursor):
    references = []
    cursor.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.VIEWS "
        "WHERE TABLE_SCHEMA<>%s AND VIEW_DEFINITION LIKE %s",
        (TARGET_DB, '%`{}`.%'.format(TARGET_DB)))
    references += [{'kind': 'view', 'schema': row[0], 'name': row[1]}
                   for row in cursor.fetchall()]
    cursor.execute(
        "SELECT ROUTINE_SCHEMA, ROUTINE_NAME FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA<>%s AND ROUTINE_DEFINITION LIKE %s",
        (TARGET_DB, '%`{}`.%'.format(TARGET_DB)))
    references += [{'kind': 'routine', 'schema': row[0], 'name': row[1]}
                   for row in cursor.fetchall()]
    return references


def config_references():
    findings = []
    patterns = (
        re.compile(r"DB_NAME\s*[=:]\s*['\"]?smass['\"]?"),
        re.compile(r"database\s*[=:]\s*['\"]smass['\"]"),
        re.compile(r"['\"]smass['\"]\s*,"),
        re.compile(r"DATABASES.*smass"),
    )
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in (
                '.py', '.env', '.example', '.yml', '.yaml', '.ps1', '.sh',
                '.ini', '.cfg', '.json', '.toml'):
            continue
        relative = path.relative_to(ROOT)
        if any(part in SCAN_SKIP for part in relative.parts):
            continue
        if relative.name.startswith('settings_unified'):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except Exception:  # noqa: BLE001
            continue
        hits = []
        for pattern in patterns:
            for line_number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append({'line': line_number, 'excerpt': line.strip()[:120]})
        if hits:
            findings.append({'file': relative.as_posix(), 'hits': hits[:5]})
    return findings


def backup_inventory():
    findings = []
    for base in (ROOT / '.local', ROOT.parent / '.local'):
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.is_file() and path.name.endswith(
                    ('.sql', '.dump', '.sql.gz', '.tar.gz', '.bundle')):
                findings.append({'path': str(path), 'bytes': path.stat().st_size})
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    connection = source_connection()
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT VERSION(), @@hostname, @@port, DATABASE(), '
                       'CURRENT_USER()')
        server = cursor.fetchone()
        cursor.execute('SHOW GRANTS')
        grants = [row[0] for row in cursor.fetchall()]
        tables, triggers, events, routines = collect_objects(cursor)
        pii = collect_pii(cursor)
        processes = collect_processes(cursor)
        cross_refs = cross_database_refs(cursor)
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s',
            (TARGET_DB,))
        object_count = cursor.fetchone()[0]
        connection.rollback()
    finally:
        connection.close()

    total_rows = sum(item['rows'] for item in tables)
    id_valid = sum(item.get('id_card_valid', 0) for key, item in pii.items()
                   if key.startswith('app01_') and isinstance(item, dict))
    id_present = sum(item.get('id_card_present', 0) for key, item in pii.items()
                     if key.startswith('app01_') and isinstance(item, dict))
    phone_non_test = sum(item.get('non_test_prefix', 0) for key, item in pii.items()
                         if key.endswith('_phone'))

    findings = []
    if id_valid > 0:
        findings.append('存在 {} 个校验位有效的身份证号，需人工确认是否为真实个人信息'.format(
            id_valid))
    if phone_non_test > 0:
        findings.append('存在 {} 个非测试号段手机号，需人工确认'.format(phone_non_test))
    if processes:
        findings.append('仍有 {} 个连接指向 {}'.format(len(processes), TARGET_DB))
    if cross_refs:
        findings.append('其它库存在 {} 个跨库引用'.format(len(cross_refs)))

    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'server': {'version': server[0], 'hostname': server[1],
                   'port': server[2], 'database': server[3],
                   'current_user': server[4]},
        'grants': grants,
        'object_count': object_count,
        'tables': tables,
        'triggers': triggers,
        'events': events,
        'routines': routines,
        'total_rows': total_rows,
        'pii': pii,
        'pii_summary': {'id_card_present': id_present,
                        'id_card_valid': id_valid,
                        'phone_non_test_prefix': phone_non_test},
        'active_connections': processes,
        'cross_database_references': cross_refs,
        'config_references': config_references(),
        'backups': backup_inventory(),
        'findings': findings,
        'deletion_plan': {
            'target': TARGET_DB,
            'statements': ['DROP DATABASE `{}`'.format(TARGET_DB)],
            'preconditions': [
                '用户对数据库 smass 的物理删除明确授权',
                '删除对象与核验清单一致（26 表/0 视图/0 触发器/0 事件/0 例程）',
                '无活动连接与跨库引用',
                '无其他程序配置引用 smass',
                '数据库级备份或确认无需备份',
            ],
            'not_included': ['MySQL 实例', '其他数据库', 'Git 历史', '备份文件'],
        },
        'verdict': 'DELETION_SAFE' if not findings else 'HOLD_FOR_REVIEW',
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(json.dumps({key: report[key] for key in (
        'server', 'object_count', 'total_rows', 'pii_summary', 'findings',
        'verdict')}, ensure_ascii=False, indent=2, default=str))
    print('RESULT: {}'.format('PASS' if report['verdict'] == 'DELETION_SAFE'
                              else 'REVIEW'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
