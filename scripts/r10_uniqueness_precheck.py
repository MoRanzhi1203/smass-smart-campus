"""H2 预检：检查唯一性不变量是否已被现有数据违反。

只读查询，不修改任何数据。发现重复时打印报告并返回非零，
迁移前置检查用。

不变量：
1. ``r21_account_accountrole``：同一 ``(account_id, role)`` 至多一条 ``revoked_at IS NULL``
2. ``smass_workflow_approvaltask``：同一 ``(instance_id, node_id)`` 至多一条 ``status='open'``

用法：
    conda run -n smass python scripts/r10_uniqueness_precheck.py
    conda run -n smass python scripts/r10_uniqueness_precheck.py --json
"""
import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r10')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402

QUERIES = [
    {
        'id': 'active_role',
        'table': 'r21_account_accountrole',
        'sql': """
            SELECT account_id, role, COUNT(*) AS cnt
            FROM r21_account_accountrole
            WHERE revoked_at IS NULL
            GROUP BY account_id, role
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
        """,
        'invariant': '同一账号同一角色至多一个 active 记录',
    },
    {
        'id': 'open_task',
        'table': 'smass_workflow_approvaltask',
        'sql': """
            SELECT instance_id, node_id, COUNT(*) AS cnt
            FROM smass_workflow_approvaltask
            WHERE status = 'open'
            GROUP BY instance_id, node_id
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
        """,
        'invariant': '同一实例同一节点至多一个 open 任务',
    },
]


def table_exists(name):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            [name],
        )
        return cur.fetchone()[0] > 0


def run_checks():
    results = []

    for check in QUERIES:
        if not table_exists(check['table']):
            results.append({
                'id': check['id'],
                'table': check['table'],
                'invariant': check['invariant'],
                'exists': False,
                'duplicates': [],
                'count': 0,
                'ok': True,
                'note': '表不存在（该模块未迁移到此库）',
            })
            continue

        with connection.cursor() as cur:
            cur.execute(check['sql'])
            rows = cur.fetchall()

        duplicates = [
            {'key': [str(v) for v in row[:-1]], 'count': int(row[-1])}
            for row in rows
        ]

        results.append({
            'id': check['id'],
            'table': check['table'],
            'invariant': check['invariant'],
            'exists': True,
            'duplicates': duplicates[:20],
            'count': len(duplicates),
            'ok': not duplicates,
            'note': '' if not duplicates else '存在重复，禁止建唯一索引',
        })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    db = connection.settings_dict['NAME']
    results = run_checks()
    ok = all(item['ok'] for item in results)

    payload = {'database': db, 'ok': ok, 'checks': results}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print('database : {}'.format(db))
        print('ok       : {}'.format(ok))
        for item in results:
            tag = 'PASS' if item['ok'] else 'FAIL'
            print('  [{}] {} ({})'.format(tag, item['id'], item['table']))
            print('         不变量: {}'.format(item['invariant']))
            if item['note']:
                print('         说明: {}'.format(item['note']))
            for dup in item['duplicates'][:5]:
                print('         重复: key={} count={}'.format(dup['key'], dup['count']))

    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
