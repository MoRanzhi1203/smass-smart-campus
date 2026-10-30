#!/usr/bin/env python
"""FINAL 正式库只读指纹（严格只读，任何写语句都会被拒绝）。

用法::

    python scripts/s25_db_fingerprint.py                     # 采集指纹
    python scripts/s25_db_fingerprint.py --json out.json
    python scripts/s25_db_fingerprint.py --compare baseline.json
    python scripts/s25_db_fingerprint.py --self-test

安全约束
--------
- 只允许 ``SELECT`` / ``SHOW`` / ``DESC`` / ``EXPLAIN`` 前缀，其余一律抛错；
- 连接后立即 ``SET SESSION TRANSACTION READ ONLY``（MySQL 8 支持）；
- 不执行任何 DDL/DML，不创建临时表，不写文件到数据库目录；
- 结果只落在本地 evidence 目录。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT.parent / '.local' / 'evidence' / 'final'

#: 允许的只读前缀
READONLY_PREFIXES = ('select', 'show', 'desc', 'describe', 'explain')

#: 关键表（内容指纹）
KEY_TABLES = (
    'django_migrations',
    'r21_account_account',
    'app01_admin',
    'app01_student',
    'app01_teacher',
)

#: 豁免库名（正式库只读，禁止指向测试/演练库）
FORMAL_DB_PREFIX = 'smass'


class ReadOnlyViolation(RuntimeError):
    pass


def is_readonly(sql):
    text = str(sql or '').strip().lower()
    if not text:
        return False
    if text.startswith('set '):
        # 仅允许设置会话只读与超时
        return text.startswith('set session transaction read only') or \
            text.startswith('set session max_execution_time')
    return text.startswith(READONLY_PREFIXES)


def connect(cfg, database=None):
    import pymysql  # noqa: PLC0415
    connection = pymysql.connect(
        host=str(cfg['HOST'] or '127.0.0.1'), port=int(cfg['PORT'] or 3306),
        user=str(cfg['USER']), password=str(cfg['PASSWORD']),
        database=database, charset='utf8mb4', autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION READ ONLY')
    return connection


def exec_readonly(cursor, sql):
    if not is_readonly(sql):
        raise ReadOnlyViolation('拒绝非只读语句：{}'.format(str(sql)[:80]))
    cursor.execute(sql)
    return cursor


def db_config():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings')
    import django  # noqa: PLC0415
    django.setup()
    from django.conf import settings  # noqa: PLC0415
    return dict(settings.DATABASES['default'])


def table_fingerprint(cursor, database, table):
    exec_readonly(cursor, 'SHOW CREATE TABLE `{}`'.format(table))
    row = cursor.fetchone()
    ddl = row[1] if row and len(row) > 1 else ''
    structure = hashlib.sha256(str(ddl).encode('utf-8')).hexdigest()[:16]

    exec_readonly(cursor, 'SELECT COUNT(*) FROM `{}`'.format(table))
    count = int(cursor.fetchone()[0])

    data_digest = None
    if table in KEY_TABLES:
        exec_readonly(cursor, 'SELECT * FROM `{}`'.format(table))
        columns = [item[0] for item in cursor.description]
        digest = hashlib.sha256()
        for record in cursor.fetchall():
            payload = {}
            for name, value in zip(columns, record):
                if isinstance(value, (bytes, bytearray)):
                    value = value.hex()
                payload[name] = value
            digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     default=str).encode('utf-8'))
        data_digest = digest.hexdigest()[:16]
    return {'rows': count, 'structure': structure, 'data': data_digest}


def fingerprint():
    cfg = db_config()
    database = str(cfg['NAME'])
    if not database.startswith(FORMAL_DB_PREFIX):
        raise SystemExit('拒绝非正式库：{!r}'.format(database))
    if database.startswith('smass_') and 'formal' not in database:
        # 正式库为 ``smass``；带下划线的是隔离库
        raise SystemExit('拒绝隔离库：{!r}（本脚本只用于正式库）'.format(database))

    connection = connect(cfg, database)
    report = {
        'started_utc': datetime.now(dt_timezone.utc).isoformat(),
        'database': database,
        'readonly': True,
        'tables': {},
    }
    try:
        with connection.cursor() as cursor:
            exec_readonly(cursor, 'SELECT VERSION()')
            report['server_version'] = cursor.fetchone()[0]
            exec_readonly(cursor, 'SELECT DATABASE()')
            report['current_database'] = cursor.fetchone()[0]
            exec_readonly(
                cursor,
                "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
                "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = "
                "'{}'".format(database))
            row = cursor.fetchone()
            report['charset'] = row[0] if row else None
            report['collation'] = row[1] if row else None

            exec_readonly(cursor, 'SHOW TABLES')
            tables = sorted(item[0] for item in cursor.fetchall())
            report['table_count'] = len(tables)
            for table in tables:
                report['tables'][table] = table_fingerprint(cursor, database, table)
    finally:
        connection.close()

    combined = hashlib.sha256()
    for table in sorted(report['tables']):
        payload = report['tables'][table]
        combined.update('{}:{}:{}:{}'.format(
            table, payload['rows'], payload['structure'], payload['data']).encode('utf-8'))
    report['db_fingerprint'] = combined.hexdigest()
    report['finished_utc'] = datetime.now(dt_timezone.utc).isoformat()
    return report


def compare(current, baseline_path):
    baseline = json.loads(Path(baseline_path).read_text(encoding='utf-8'))
    changes = []
    if current['db_fingerprint'] != baseline.get('db_fingerprint'):
        for table in sorted(set(current['tables']) | set(baseline.get('tables', {}))):
            now = current['tables'].get(table)
            before = baseline.get('tables', {}).get(table)
            if now != before:
                changes.append({'table': table, 'before': before, 'after': now})
    return {'identical': not changes, 'changes': changes}


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(is_readonly('SELECT 1'), 'SELECT 允许')
    check(is_readonly('  show tables '), 'SHOW 允许')
    check(is_readonly('SHOW CREATE TABLE x'), 'SHOW CREATE 允许')
    check(is_readonly('DESC x'), 'DESC 允许')
    check(not is_readonly('INSERT INTO x VALUES (1)'), 'INSERT 拒绝')
    check(not is_readonly('UPDATE x SET a=1'), 'UPDATE 拒绝')
    check(not is_readonly('DELETE FROM x'), 'DELETE 拒绝')
    check(not is_readonly('DROP TABLE x'), 'DROP 拒绝')
    check(not is_readonly('ALTER TABLE x ADD c INT'), 'ALTER 拒绝')
    check(not is_readonly(''), '空语句拒绝')
    check(is_readonly('SET SESSION TRANSACTION READ ONLY'), '只读会话设置允许')

    for message in failures:
        print('SELF-TEST FAIL:', message)
    if not failures:
        print('SELF-TEST PASS (11 checks)')
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description='正式库只读指纹')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--compare', dest='baseline', default='')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    report = fingerprint()
    if args.baseline:
        report['comparison'] = compare(report, args.baseline)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    path = Path(args.json_path) if args.json_path else EVIDENCE / 'db_fingerprint.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

    print('库：{}（{}） 表 {} 张'.format(
        report['database'], report['server_version'], report['table_count']))
    print('字符集：{} / {}'.format(report['charset'], report['collation']))
    print('库指纹：{}'.format(report['db_fingerprint']))
    if args.baseline:
        print('与基线一致：{}'.format(report['comparison']['identical']))
    print('RESULT: PASS（只读）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
