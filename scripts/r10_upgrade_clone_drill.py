"""H5：现有 26 表结构 -> R10 升级 -> 备份 -> 恢复 演练。

安全前提
--------
- 源库 ``smass`` **只读**：本脚本只执行 `mysqldump --no-data`（结构化，无数据行）。
- 不复制任何真实姓名、密码哈希、行数据到克隆、日志或仓库。
- 克隆库名唯一且必须不存在；已存在即拒绝，绝不覆盖。

流程
----
1. 快照 `smass` 表数与关键行数
2. 用只读账号验证写入被拒（不修改任何行）
3. `mysqldump --no-data smass` -> 新建 ``smass_h5_clone_<ts>``
4. 记录克隆初始表数（应为 26）
5. 用 ``settings_h5`` 对克隆应用 R10 迁移链
6. 记录升级后表数、迁移记录数、关键表是否健在
7. `mysqldump` 备份克隆 -> 恢复到 ``smass_h5_restore_<ts>``
8. 对比表数与结构指纹
9. 复检 `smass` 未变化

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/r10_upgrade_clone_drill.py
"""
import argparse
import hashlib
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
READONLY_USER = os.environ.get('SMASS_RO_USER', 'smass_g5_ro')
READONLY_PASSWORD = os.environ.get('SMASS_RO_PASSWORD', '')

BASE = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
MYSQL_BIN = Path(r'D:\mysql-8.0.18-winx64\bin')
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'smass_h5_drill'

SOURCE_DB = 'smass'
ALLOWED_PREFIXES = ('smass_h5_',)


def admin_conn(db=None):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4')


def db_exists(name):
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',
                [name])
            return cur.fetchone()[0] > 0
    finally:
        conn.close()


def table_list(db):
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', [db])
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def schema_fingerprint(db):
    """结构指纹：表名 + 列名/类型，排序后 sha256。"""
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, '
                'COLUMN_KEY, EXTRA FROM information_schema.COLUMNS '
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION',
                [db])
            rows = cur.fetchall()
    finally:
        conn.close()

    payload = '\n'.join('|'.join(str(c) for c in row) for row in rows)
    return {
        'sha256': hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32],
        'columns': len(rows),
    }


def row_counts(db, tables):
    conn = admin_conn(db)
    counts = {}
    try:
        with conn.cursor() as cur:
            for table in tables:
                try:
                    cur.execute('SELECT COUNT(*) FROM `{}`'.format(table))
                    counts[table] = cur.fetchone()[0]
                except Exception:  # noqa: BLE001
                    counts[table] = None
    finally:
        conn.close()
    return counts


def source_snapshot():
    tables = table_list(SOURCE_DB)
    key_tables = [t for t in tables if t in (
        'app01_admin', 'app01_student', 'app01_teacher')]
    counts = row_counts(SOURCE_DB, key_tables)
    return {
        'tables': len(tables),
        'table_names': tables,
        'key_counts': counts,
        'fingerprint': schema_fingerprint(SOURCE_DB),
    }


def verify_readonly_denied():
    """用只读账号尝试写，必须被拒。不触碰任何真实行。"""
    if not READONLY_PASSWORD:
        return {
            'tested': False,
            'reason': '未提供 SMASS_RO_PASSWORD，跳过写拒绝测试',
        }

    try:
        conn = pymysql.connect(host=HOST, user=READONLY_USER,
                               password=READONLY_PASSWORD,
                               database=SOURCE_DB, charset='utf8mb4')
    except Exception as exc:  # noqa: BLE001
        return {'tested': False,
                'reason': '只读账号连接失败: {}'.format(type(exc).__name__)}

    try:
        with conn.cursor() as cur:
            # 只读探测：SELECT 应成功
            cur.execute('SELECT 1')
            cur.fetchone()
            select_ok = True

            # 写入探测：CREATE TEMPORARY TABLE 不改真实数据，
            # 但对只读账号应被拒绝
            denied = False
            detail = ''
            try:
                cur.execute('CREATE TEMPORARY TABLE _h5_probe (id INT)')
            except Exception as exc:  # noqa: BLE001
                denied = True
                detail = str(exc)[:120]
            else:
                denied = False
                detail = '临时表创建成功（说明该账号并非只读）'
    finally:
        conn.close()

    return {
        'tested': True,
        'user': READONLY_USER,
        'select_ok': select_ok,
        'write_denied': denied,
        'detail': detail,
    }


def run_mysql(args, stdin_file=None):
    cmd = [str(MYSQL_BIN / 'mysql.exe'), '--host', HOST, '--user', ADMIN_USER,
           '--password={}'.format(ADMIN_PASSWORD)] + args
    if stdin_file:
        with open(stdin_file, 'rb') as handle:
            return subprocess.run(cmd, stdin=handle, capture_output=True)
    return subprocess.run(cmd, capture_output=True)


def run_dump(db, out_path, no_data=False, tables=None, no_create_info=False):
    env = dict(os.environ)
    env['MYSQL_PWD'] = ADMIN_PASSWORD
    cmd = [str(MYSQL_BIN / 'mysqldump.exe'),
           '--single-transaction', '--no-tablespaces', '--skip-triggers',
           '--set-gtid-purged=OFF',
           '--host', HOST, '--user', ADMIN_USER]
    if no_data:
        cmd.append('--no-data')
    if no_create_info:
        cmd.append('--no-create-info')
    cmd.append(db)
    if tables:
        cmd.extend(tables)
    with open(out_path, 'wb') as handle:
        return subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, env=env)


def run_migrate(db_name):
    env = dict(os.environ)
    env['H5_DB'] = db_name
    started = time.perf_counter()
    result = subprocess.run(
        [PYTHON, 'manage.py', 'migrate', '--noinput',
         '--settings=smass.settings_h5'],
        cwd=str(BASE), capture_output=True, text=True, env=env)
    return {
        'exit': result.returncode,
        'seconds': round(time.perf_counter() - started, 1),
        'tail': (result.stdout or result.stderr).strip().splitlines()[-3:],
    }


def migration_count(db):
    conn = admin_conn(db)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM django_migrations')
            return cur.fetchone()[0]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep', action='store_true', help='保留克隆库（默认保留）')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    clone = 'smass_h5_clone_{}'.format(stamp)
    restore = 'smass_h5_restore_{}'.format(stamp)

    for name in (clone, restore):
        if not name.startswith(ALLOWED_PREFIXES):
            raise SystemExit('拒绝：库名必须命中 {}'.format(ALLOWED_PREFIXES))
        if db_exists(name):
            raise SystemExit('拒绝：库已存在 {}（不覆盖）'.format(name))

    report = {'source': SOURCE_DB, 'clone': clone, 'restore': restore,
              'steps': []}

    # ---- 1. 源库快照 ----
    before = source_snapshot()
    report['source_before'] = {'tables': before['tables'],
                               'key_counts': before['key_counts'],
                               'fingerprint': before['fingerprint']}
    report['steps'].append({'step': 'snapshot_source', 'ok': True,
                            'tables': before['tables']})

    # ---- 2. 只读验证 ----
    ro = verify_readonly_denied()
    report['readonly_check'] = ro
    report['steps'].append({
        'step': 'readonly_write_denied',
        'ok': (not ro.get('tested')) or bool(ro.get('write_denied')),
        'detail': ro,
    })

    # ---- 3. schema-only 克隆 ----
    dump_path = OUT_DIR / 'source_schema_{}.sql'.format(stamp)
    result = run_dump(SOURCE_DB, dump_path, no_data=True)
    if result.returncode != 0:
        raise SystemExit('mysqldump 失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(clone))
        conn.commit()
    finally:
        conn.close()

    result = run_mysql([clone], stdin_file=dump_path)
    if result.returncode != 0:
        raise SystemExit('导入克隆结构失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    # 关键补充：django_migrations 的**记录**必须一并复制，
    # 否则 Django 认为所有迁移都未应用，会尝试重建已存在的表并失败
    # （实测 Table 'django_content_type' already exists / 'app01_admin' already exists）。
    # 该表只含 app 名 + 迁移名 + 时间，不含任何 PII。
    mig_dump = OUT_DIR / 'django_migrations_{}.sql'.format(stamp)
    result = run_dump(SOURCE_DB, mig_dump, no_create_info=True,
                      tables=['django_migrations'])
    if result.returncode != 0:
        raise SystemExit('导出迁移记录失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    result = run_mysql([clone], stdin_file=mig_dump)
    if result.returncode != 0:
        raise SystemExit('导入迁移记录失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    clone_mig_rows = migration_count(clone)
    report['clone_migrations_copied'] = clone_mig_rows

    clone_tables_before = table_list(clone)
    report['clone_before'] = {
        'tables': len(clone_tables_before),
        'dump_bytes': dump_path.stat().st_size,
    }
    report['steps'].append({'step': 'clone_schema_only',
                            'ok': len(clone_tables_before) == before['tables'],
                            'tables': len(clone_tables_before)})

    # ---- 4. 应用 R10 迁移 ----
    mig = run_migrate(clone)
    report['migrate'] = mig
    report['steps'].append({
        'step': 'apply_r10_migrations',
        'ok': mig['exit'] == 0,
        'seconds': mig['seconds'],
        'tail': mig['tail'],
    })

    clone_tables_after = table_list(clone)
    report['clone_after'] = {
        'tables': len(clone_tables_after),
        'migrations': migration_count(clone) if 'django_migrations' in clone_tables_after else None,
    }

    # 关键表健在
    required = ['auth_user', 'app01_admin', 'app01_student', 'app01_teacher',
                'r21_account_account', 'r22_account_accountauditevent',
                'django_migrations']
    missing = [t for t in required if t not in clone_tables_after]
    report['steps'].append({'step': 'key_tables_survive',
                            'ok': not missing, 'missing': missing})

    # H2 生成列索引是否随迁移进入克隆
    conn = admin_conn(clone)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND INDEX_NAME IN "
                "('uq_r21_active_role','uq_r6_open_task') AND NON_UNIQUE=0",
                [clone])
            h2_indexes = cur.fetchone()[0]
    finally:
        conn.close()

    report['clone_after']['h2_index_rows'] = h2_indexes
    report['steps'].append({'step': 'h2_indexes_present',
                            'ok': h2_indexes > 0,
                            'rows': h2_indexes})

    # ---- 5. 备份 + 恢复 ----
    backup_path = OUT_DIR / 'clone_upgraded_{}.sql'.format(stamp)
    result = run_dump(clone, backup_path, no_data=False)
    if result.returncode != 0:
        raise SystemExit('备份升级后克隆失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(restore))
        conn.commit()
    finally:
        conn.close()

    result = run_mysql([restore], stdin_file=backup_path)
    if result.returncode != 0:
        raise SystemExit('恢复失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:300]))

    restore_tables = table_list(restore)
    report['restore'] = {
        'tables': len(restore_tables),
        'backup_bytes': backup_path.stat().st_size,
    }
    report['steps'].append({
        'step': 'backup_and_restore',
        'ok': len(restore_tables) == len(clone_tables_after),
        'clone_tables': len(clone_tables_after),
        'restore_tables': len(restore_tables),
    })

    # ---- 6. 结构指纹对比（升级后克隆 vs 恢复库）----
    fp_clone = schema_fingerprint(clone)
    fp_restore = schema_fingerprint(restore)
    report['fingerprint'] = {'clone': fp_clone, 'restore': fp_restore}
    report['steps'].append({
        'step': 'fingerprint_match',
        'ok': fp_clone['sha256'] == fp_restore['sha256'],
        'clone': fp_clone['sha256'],
        'restore': fp_restore['sha256'],
    })

    # ---- 7. 源库未变 ----
    after = source_snapshot()
    report['source_after'] = {'tables': after['tables'],
                              'key_counts': after['key_counts'],
                              'fingerprint': after['fingerprint']}
    unchanged = (
        after['tables'] == before['tables']
        and after['key_counts'] == before['key_counts']
        and after['fingerprint']['sha256'] == before['fingerprint']['sha256']
    )
    report['steps'].append({'step': 'source_unchanged', 'ok': unchanged})

    report['ok'] = all(step.get('ok') for step in report['steps'])
    report['scope_note'] = (
        '本演练为 schema-only：克隆复制表结构，不含任何真实行。'
        '因此证明"26 表结构可升级到 R10 并可备份恢复"，'
        '但**不证明**真实历史行（含 app01 的真实姓名/哈希）的数据迁移；'
        '后者需要单独授权才能复制真实 PII。')
    report['note'] = '库不自动删除；清理需另行批准'

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
