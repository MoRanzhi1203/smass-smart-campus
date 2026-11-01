#!/usr/bin/env python
"""V2.2 退役审计（只读）：三库状态、活动连接、引用扫描、campus 备份能力。

    python scripts/v22_retire_audit.py --json out.json

不执行任何 DROP / DELETE。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_campus')

OLD_DBS = ('smass_product_dev', 'smass_simulation', 'smass_unified_verify')
NEW_DB = 'smass_campus'


def db_conn():
    import pymysql

    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', '3306')),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)


def table_count(cursor, name):
    cursor.execute(
        'SELECT COUNT(1) AS n FROM information_schema.tables '
        'WHERE table_schema=%s', [name])
    return cursor.fetchone()['n']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path',
                        default=str(ROOT / '.local/evidence/v22/retire_audit.json'))
    args = parser.parse_args()

    conn = db_conn()
    report = {'old_databases': {}, 'new_database': {}, 'active_connections': [],
              'references': {}, 'backup_tool': None, 'note': ''}
    with conn.cursor() as cursor:
        cursor.execute('SHOW DATABASES')
        names = [row['Database'] for row in cursor.fetchall()]
        report['new_database'] = {'name': NEW_DB, 'exists': NEW_DB in names,
                                  'tables': table_count(cursor, NEW_DB)}
        for name in OLD_DBS:
            report['old_databases'][name] = {
                'exists': name in names,
                'tables': table_count(cursor, name) if name in names else 0,
                'status': 'LOGICALLY_RETIRED' if name in names else 'ABSENT',
            }
        cursor.execute(
            'SELECT ID, USER, DB, COMMAND, TIME, STATE, INFO '
            'FROM information_schema.processlist WHERE DB IN (%s, %s, %s)',
            list(OLD_DBS))
        report['active_connections'] = [
            {'id': row['ID'], 'user': row['USER'], 'db': row['DB'],
             'command': row['COMMAND'], 'time': row['TIME']}
            for row in cursor.fetchall()]
    conn.close()

    # 代码/文档引用扫描（只统计，不修改）
    hits = {}
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in ('.git', '.local'):
            continue
        if path.suffix not in ('.py', '.md', '.ps1', '.sh', '.yml', '.yaml',
                               '.toml', '.example'):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for name in OLD_DBS:
            if name in text:
                hits.setdefault(name, []).append(str(path.relative_to(ROOT)))
    report['references'] = {name: paths[:40] for name, paths in hits.items()}
    report['backup_tool'] = 'mysqldump' if shutil.which('mysqldump') else None
    if report['backup_tool'] is None:
        report['note'] = ('未检测到 mysqldump；campus 独立备份尚未生成，'
                          '物理删除前必须先完成备份。')

    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
