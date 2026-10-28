"""R10-02：全新隔离环境安装预检与从零安装。

流程：
1. 创建**全新**库 ``smass_r10_install_<ts>``（存在则拒绝）；
2. 应用全部迁移；
3. 校验表数量与关键模块表存在；
4. 迁移一致性（无 pending）；
5. 输出安装报告（耗时、表数、模块清单）。

安全：只操作 ``smass_r10_`` 前缀库，不触碰 ``smass``。

用法：
    $env:SMASS_DB_PASSWORD='<pwd>'
    conda run -n smass python scripts/r10_install.py
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

REQUIRED_TABLES = (
    'smass_organization_organizationunit',
    'smass_organization_studentrecord',
    'smass_academic_academicterm',
    'smass_academic_teachingsection',
    'smass_workflow_workflowinstance',
    'smass_analytics_metricdefinition',
    'smass_api_serviceaccount',
    'smass_operations_requestmetric',
)


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
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME',
                [db],
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def run(cmd, env=None):
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, env=env)
    return result, round(time.perf_counter() - started, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db')
    args = parser.parse_args()

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    db_name = args.db or 'smass_r10_install_{}'.format(stamp)

    if not db_name.startswith(ALLOWED_PREFIXES):
        raise SystemExit('拒绝：库名必须命中 {}，当前 {!r}'.format(
            ALLOWED_PREFIXES, db_name))
    if db_exists(db_name):
        raise SystemExit('拒绝：库已存在 {}（不覆盖）'.format(db_name))

    report = {'database': db_name, 'steps': []}

    # 1) 创建空库
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci'.format(db_name)
            )
        conn.commit()
    finally:
        conn.close()
    report['steps'].append({'step': 'create_database', 'ok': True})

    # 2) 应用迁移
    env = dict(os.environ)
    env['R10_DB'] = db_name
    result, seconds = run(
        [PYTHON, 'manage.py', 'migrate', '--noinput', '--settings=smass.settings_r10'],
        env=env,
    )
    report['steps'].append({
        'step': 'migrate', 'ok': result.returncode == 0, 'seconds': seconds,
        'tail': (result.stdout or result.stderr).strip().splitlines()[-2:],
    })

    # 3) 表存在性
    found = set(tables(db_name))
    missing = [table for table in REQUIRED_TABLES if table not in found]
    report['table_count'] = len(found)
    report['missing_tables'] = missing
    report['steps'].append({'step': 'tables', 'ok': not missing})

    # 4) 迁移一致性（无 pending）
    result, seconds = run(
        [PYTHON, 'manage.py', 'makemigrations', '--check', '--dry-run',
         '--settings=smass.settings_r10'],
        env=env,
    )
    report['steps'].append({
        'step': 'migration_consistency',
        'ok': result.returncode == 0,
        'seconds': seconds,
    })

    report['ok'] = all(step['ok'] for step in report['steps'])
    report['note'] = ('安装到全新隔离库；正式环境部署需单独授权。'
                      '如需清理请另行批准（本脚本不删库）')

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
