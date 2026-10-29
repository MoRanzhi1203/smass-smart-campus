#!/usr/bin/env python
"""正式数据库只读指纹（证明「零写入」）。

只执行 SELECT / SHOW / information_schema 查询，绝不写库。
用于：
- S0：回归测试前后对比，证明正式 `smass` 库未被写入；
- S08：备份恢复演练的 schema/数据双指纹基础。

用法:
    python scripts/db_fingerprint.py                    # 默认正式 settings
    python scripts/db_fingerprint.py --settings=smass.settings_r10
    python scripts/db_fingerprint.py --json
    python scripts/db_fingerprint.py --compare before.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

#: 用于「零写入」证据的关键表（存在才统计）
KEY_TABLES = (
    'app01_student', 'app01_teacher', 'app01_admin',
    'app01_classes', 'app01_college', 'app01_major',
    'auth_user', 'django_migrations', 'django_session',
)


def fingerprint() -> dict:
    import django
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute('SELECT DATABASE()')
        db = cur.fetchone()[0]

        cur.execute(
            'SELECT table_name, table_rows, engine, table_collation '
            'FROM information_schema.tables WHERE table_schema = %s '
            'ORDER BY table_name', [db],
        )
        tables = [
            {'name': r[0], 'approx_rows': r[1], 'engine': r[2], 'collation': r[3]}
            for r in cur.fetchall()
        ]

        # 精确行数（information_schema.table_rows 对 InnoDB 是估算值）
        exact: dict[str, int] = {}
        for t in KEY_TABLES:
            try:
                cur.execute('SELECT COUNT(*) FROM `{}`'.format(t))
                exact[t] = cur.fetchone()[0]
            except Exception as exc:  # noqa: BLE001 - 表不存在时记录而非中断
                exact[t] = -1
                tables.append({'note': f'count failed {t}: {type(exc).__name__}'})

        # schema 指纹：列定义的有序摘要
        cur.execute(
            'SELECT table_name, column_name, column_type, is_nullable, column_key, column_default '
            'FROM information_schema.columns WHERE table_schema = %s '
            'ORDER BY table_name, ordinal_position', [db],
        )
        cols = cur.fetchall()

    schema_blob = '\n'.join('|'.join('' if v is None else str(v) for v in row) for row in cols)
    schema_sha = hashlib.sha256(schema_blob.encode('utf-8')).hexdigest()

    tables_blob = '\n'.join(f"{t['name']}|{t['engine']}|{t['collation']}" for t in tables)
    tables_sha = hashlib.sha256(tables_blob.encode('utf-8')).hexdigest()

    rows_blob = '\n'.join(f'{k}={v}' for k, v in sorted(exact.items()))
    rows_sha = hashlib.sha256(rows_blob.encode('utf-8')).hexdigest()

    return {
        'database': db,
        'table_count': len(tables),
        'tables': [t['name'] for t in tables],
        'column_count': len(cols),
        'exact_row_counts': exact,
        'schema_sha256': schema_sha,
        'tables_sha256': tables_sha,
        'rows_sha256': rows_sha,
        'combined_sha256': hashlib.sha256(
            (schema_sha + tables_sha + rows_sha).encode()).hexdigest(),
    }


def compare(before: dict, after: dict) -> list[str]:
    problems: list[str] = []
    for key in ('database', 'table_count', 'column_count',
                'schema_sha256', 'tables_sha256', 'rows_sha256', 'combined_sha256'):
        if before.get(key) != after.get(key):
            problems.append(f'{key}: {before.get(key)!r} -> {after.get(key)!r}')
    b_rows = before.get('exact_row_counts') or {}
    a_rows = after.get('exact_row_counts') or {}
    for t in sorted(set(b_rows) | set(a_rows)):
        if b_rows.get(t) != a_rows.get(t):
            problems.append(f'rows[{t}]: {b_rows.get(t)} -> {a_rows.get(t)}')
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description='正式库只读指纹')
    ap.add_argument('--settings', default='smass.settings')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--out', default='')
    ap.add_argument('--compare', default='', help='与先前保存的 JSON 对比')
    args = ap.parse_args()

    os.environ['DJANGO_SETTINGS_MODULE'] = args.settings
    import django
    django.setup()

    fp = fingerprint()

    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding='utf-8'))
        problems = compare(before, fp)
        if problems:
            print('CHANGED:')
            for p in problems:
                print('  -', p)
            return 1
        print('UNCHANGED: 指纹完全一致（正式库零写入）')
        print('combined_sha256 =', fp['combined_sha256'])
        return 0

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding='utf-8')

    if args.json:
        print(json.dumps(fp, ensure_ascii=False, indent=2))
    else:
        print(f"database      : {fp['database']}")
        print(f"table_count   : {fp['table_count']}")
        print(f"column_count  : {fp['column_count']}")
        print(f"exact rows    : {fp['exact_row_counts']}")
        print(f"schema_sha256 : {fp['schema_sha256']}")
        print(f"tables_sha256 : {fp['tables_sha256']}")
        print(f"rows_sha256   : {fp['rows_sha256']}")
        print(f"combined      : {fp['combined_sha256']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
