"""R10-03：升级与回滚演练（合成隔离库）。

思路（不触碰 ``smass``）：
1. 在全新库 ``smass_r10_upgrade_<ts>`` 安装到全部迁移；
2. 写入一条合成业务数据并记录；
3. **回滚**一个模块（默认 ``smass_analytics``）到 zero；
4. 校验：该模块表消失，**其他模块数据仍在**；
5. **重新应用**该模块迁移；
6. 校验：升级后其他模块数据依然完整，业务可继续。

这验证"模块级迁移可逆 + 数据不丢失"。

用法：
    $env:SMASS_DB_PASSWORD='<pwd>'
    conda run -n smass python scripts/r10_upgrade_drill.py
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
BASE = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

ALLOWED_PREFIXES = ('smass_r10_',)
TARGET_MODULE = 'smass_analytics'


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


def tables(db):
    conn = admin_conn(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=%s',
                [db],
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def run(cmd, env):
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, env=env)
    return result, round(time.perf_counter() - started, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db')
    parser.add_argument('--module', default=TARGET_MODULE)
    args = parser.parse_args()

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    db_name = args.db or 'smass_r10_upgrade_{}'.format(stamp)

    if not db_name.startswith(ALLOWED_PREFIXES):
        raise SystemExit('拒绝：库名必须命中 {}'.format(ALLOWED_PREFIXES))
    if db_exists(db_name):
        raise SystemExit('拒绝：库已存在 {}（不覆盖）'.format(db_name))

    env = dict(os.environ)
    env['R10_DB'] = db_name
    report = {'database': db_name, 'module': args.module, 'steps': []}

    # 1) 建库 + 安装
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci'.format(db_name)
            )
        conn.commit()
    finally:
        conn.close()

    result, seconds = run(
        [PYTHON, 'manage.py', 'migrate', '--noinput', '--settings=smass.settings_r10'], env
    )
    report['steps'].append({'step': 'install', 'ok': result.returncode == 0,
                            'seconds': seconds})

    # 2) 写入合成业务数据（组织单元，属 R4，回滚 analytics 不应影响它）
    import pymysql as _pymysql

    conn = admin_conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO smass_organization_organizationunit "
                "(code, name, unit_type, status, sort_order, created_at, updated_at) "
                "VALUES ('UPG-C1', '升级演练学院', 'college', 'active', 0, NOW(), NOW())"
            )
        conn.commit()
    finally:
        conn.close()

    before_tables = tables(db_name)
    report['tables_before'] = len(before_tables)

    # 3) 回滚目标模块
    result, seconds = run(
        [PYTHON, 'manage.py', 'migrate', args.module, 'zero', '--noinput',
         '--settings=smass.settings_r10'], env
    )
    report['steps'].append({'step': 'rollback_module', 'ok': result.returncode == 0,
                            'seconds': seconds,
                            'tail': (result.stdout or result.stderr).strip().splitlines()[-2:]})

    after_tables = tables(db_name)
    report['tables_after_rollback'] = len(after_tables)
    module_tables_removed = not any(t.startswith('smass_analytics_') for t in after_tables)
    report['steps'].append({'step': 'module_tables_dropped', 'ok': module_tables_removed})

    # 4) 其他模块数据仍在
    conn = admin_conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM smass_organization_organizationunit WHERE code='UPG-C1'"
            )
            survived = cur.fetchone()[0]
    finally:
        conn.close()
    report['other_module_data_survived'] = survived == 1
    report['steps'].append({'step': 'other_data_intact', 'ok': survived == 1})

    # 5) 重新升级
    result, seconds = run(
        [PYTHON, 'manage.py', 'migrate', '--noinput', '--settings=smass.settings_r10'], env
    )
    report['steps'].append({'step': 'reinstall', 'ok': result.returncode == 0,
                            'seconds': seconds})

    final_tables = tables(db_name)
    report['tables_after_upgrade'] = len(final_tables)
    module_tables_restored = any(t.startswith('smass_analytics_') for t in final_tables)
    report['steps'].append({'step': 'module_tables_restored', 'ok': module_tables_restored})

    # 6) 数据仍在
    conn = admin_conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM smass_organization_organizationunit WHERE code='UPG-C1'"
            )
            final_count = cur.fetchone()[0]
    finally:
        conn.close()
    report['final_data_survived'] = final_count == 1
    report['steps'].append({'step': 'final_data_intact', 'ok': final_count == 1})

    report['ok'] = all(step['ok'] for step in report['steps'])
    report['note'] = '模块级迁移可逆性演练；不含生产部署，库不自动删除'

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
