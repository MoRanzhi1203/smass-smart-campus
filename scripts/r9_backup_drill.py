"""R9-03：备份恢复演练（合成隔离库），测量 RTO 并校验一致性。

流程：
1. 用 mysqldump 备份 ``smass_r9_ops``；
2. 恢复到新库 ``smass_r9_ops_restore_<ts>``（不存在才建）；
3. 比较表数与每表行数；
4. 记录备份/恢复耗时（RTO 技术值）。

安全：只操作 ``smass_r9_*`` 前缀库；不触碰 ``smass``。

用法：
    $env:SMASS_DB_PASSWORD='<pwd>'
    conda run -n smass python scripts/r9_backup_drill.py
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pymysql

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
SOURCE_DB = 'smass_r9_ops'
MYSQL_BIN = Path(r'D:\mysql-8.0.18-winx64\bin')
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'smass_r9_backup'

ALLOWED_PREFIXES = ('smass_r9_',)


def guard(db_name):
    if not db_name.startswith(ALLOWED_PREFIXES):
        raise SystemExit('拒绝：只允许 {} 前缀库，当前 {!r}'.format(
            ALLOWED_PREFIXES, db_name))


def admin_conn(db=None):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8')


def db_exists(name):
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',
                [name],
            )
            return cur.fetchone()[0] > 0
    finally:
        conn.close()


def table_counts(db):
    conn = admin_conn(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME',
                [db],
            )
            tables = [row[0] for row in cur.fetchall()]
            counts = {}
            for table in tables:
                cur.execute('SELECT COUNT(*) FROM `{}`'.format(table))
                counts[table] = cur.fetchone()[0]
            return counts
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=SOURCE_DB)
    args = parser.parse_args()

    source = args.source
    guard(source)
    if not db_exists(source):
        print('SKIP: 源库 {} 不存在'.format(source))
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = 'smass_r9_ops_restore_{}'.format(stamp)
    guard(target)

    if db_exists(target):
        raise SystemExit('拒绝：目标库已存在 {}'.format(target))

    dump_path = OUT_DIR / 'r9_{}.sql'.format(stamp)

    # ---- 备份 ----
    env = dict(os.environ)
    env['MYSQL_PWD'] = ADMIN_PASSWORD
    started = time.perf_counter()
    result = subprocess.run(
        [str(MYSQL_BIN / 'mysqldump.exe'), '--single-transaction', '--no-tablespaces',
         '--skip-triggers', '--skip-add-drop-table',
         '--host', HOST, '--user', ADMIN_USER, source],
        stdout=open(dump_path, 'wb'), stderr=subprocess.PIPE, env=env,
    )
    backup_seconds = round(time.perf_counter() - started, 2)
    if result.returncode != 0:
        raise SystemExit('备份失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    source_counts = table_counts(source)

    # ---- 建库 + 恢复 ----
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci'.format(target)
            )
        conn.commit()
    finally:
        conn.close()

    started = time.perf_counter()
    with open(dump_path, 'rb') as handle:
        result = subprocess.run(
            [str(MYSQL_BIN / 'mysql.exe'), '--host', HOST, '--user', ADMIN_USER,
             '--password={}'.format(ADMIN_PASSWORD), target],
            stdin=handle, stderr=subprocess.PIPE,
        )
    restore_seconds = round(time.perf_counter() - started, 2)
    if result.returncode != 0:
        raise SystemExit('恢复失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    target_counts = table_counts(target)

    mismatches = {
        table: {'source': count, 'target': target_counts.get(table)}
        for table, count in source_counts.items()
        if target_counts.get(table) != count
    }

    report = {
        'source': source,
        'target': target,
        'dump_path': str(dump_path),
        'dump_bytes': dump_path.stat().st_size,
        'backup_seconds': backup_seconds,
        'restore_seconds': restore_seconds,
        'rto_seconds': restore_seconds,
        'tables_source': len(source_counts),
        'tables_target': len(target_counts),
        'mismatches': mismatches,
        'ok': not mismatches and len(source_counts) == len(target_counts),
        'note': 'RTO 为技术实测值；生产 RPO/RTO 目标需另行批准',
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
