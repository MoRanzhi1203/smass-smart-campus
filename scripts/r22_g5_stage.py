"""G5.1：只读快照 + 隔离 stage 库（绝不 DROP/覆盖任何既有库）。

流程：
1. 用**只读账号** ``mysqldump --single-transaction`` 导出 ``smass``（一致性快照）；
2. 断言目标 stage 库**不存在**（存在则换名，绝不覆盖）；
3. 创建 stage 库，用 root 恢复（写仅发生在 stage）；
4. 校验计数与 schema 指纹，输出脱敏 JSON。

用法：
    conda run -n smass python scripts/r22_g5_stage.py [--stage smass_r22_g5_stage]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pymysql

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
SOURCE_DB = 'smass'
DEFAULT_STAGE = 'smass_r22_g5_stage'

MYSQL_BIN = Path(r'D:\mysql-8.0.18-winx64\bin')
CRED_FILE = Path(os.environ.get('TEMP', '.')) / 'smass_g5_ro_credential.txt'
SNAPSHOT_FILE = Path(os.environ.get('TEMP', '.')) / 'smass_g5_snapshot.sql'

#: 只允许恢复到的前缀（fail closed）
STAGE_PREFIXES = ('smass_r22_g5_',)


def admin_conn(db=None):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8')


def load_credential():
    if not CRED_FILE.exists():
        raise SystemExit('缺少只读凭据文件，请先运行 scripts/r22_g5_ro_user.py')
    return json.loads(CRED_FILE.read_text(encoding='utf-8'))


def db_exists(name):
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                [name],
            )
            return cur.fetchone()[0] > 0
    finally:
        conn.close()


def schema_fingerprint(db):
    """对表结构做确定性指纹（表名 + 列名 + 类型，排序后 sha256）。"""
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
                "ORDER BY TABLE_NAME, COLUMN_NAME",
                [db],
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s",
                [db],
            )
            table_count = cur.fetchone()[0]
    finally:
        conn.close()

    payload = '\n'.join('|'.join(str(c) for c in row) for row in rows)
    return {
        'table_count': table_count,
        'column_count': len(rows),
        'fingerprint': hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32],
    }


def counts(db):
    conn = admin_conn(db)
    try:
        with conn.cursor() as cur:
            out = {}
            for table in ('app01_admin', 'app01_student', 'app01_teacher'):
                cur.execute('SELECT COUNT(*) FROM `{}`'.format(table))
                out[table] = cur.fetchone()[0]
            return out
    finally:
        conn.close()


def dump_snapshot(credential):
    env = dict(os.environ)
    env['MYSQL_PWD'] = credential['password']

    cmd = [
        str(MYSQL_BIN / 'mysqldump.exe'),
        '--single-transaction',      # InnoDB 一致性快照，不锁表
        '--no-tablespaces',
        '--skip-triggers',
        '--skip-add-drop-table',
        '--host', HOST,
        '--user', credential['user'],
        SOURCE_DB,
    ]

    started = datetime.now()
    with open(SNAPSHOT_FILE, 'wb') as handle:
        result = subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, env=env)
    elapsed = (datetime.now() - started).total_seconds()

    if result.returncode != 0:
        raise SystemExit('mysqldump 失败: {}'.format(result.stderr.decode('utf-8', 'replace')[:400]))

    return {
        'method': 'mysqldump --single-transaction (read-only user)',
        'started_at': started.isoformat(timespec='seconds'),
        'seconds': round(elapsed, 2),
        'bytes': SNAPSHOT_FILE.stat().st_size,
        'snapshot_path': str(SNAPSHOT_FILE),
        'in_repository': False,
    }


def create_and_restore(stage, credential):
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci'.format(stage)
            )
        conn.commit()
    finally:
        conn.close()

    # 恢复用 root（写只发生在 stage），不要用 MYSQL_PWD 里的只读账号
    cmd = [
        str(MYSQL_BIN / 'mysql.exe'),
        '--host', HOST,
        '--user', ADMIN_USER,
        '--password={}'.format(ADMIN_PASSWORD),
        stage,
    ]
    with open(SNAPSHOT_FILE, 'rb') as handle:
        result = subprocess.run(cmd, stdin=handle, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise SystemExit('恢复失败: {}'.format(result.stderr.decode('utf-8', 'replace')[:400]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', default=DEFAULT_STAGE)
    args = parser.parse_args()
    stage = args.stage

    if not stage.startswith(STAGE_PREFIXES):
        raise SystemExit('拒绝：stage 库名必须命中 {}，当前 {!r}'.format(STAGE_PREFIXES, stage))
    if stage == SOURCE_DB or stage in ('smass_r22_b_switch', 'smass_r21_proto',
                                       'smass_r22_proto', 'smass_r22_b_proto',
                                       'smass_proto_account', 'smass_proto_user_model'):
        raise SystemExit('拒绝：不能把既有库当作 stage 目标')

    credential = load_credential()

    if db_exists(stage):
        raise SystemExit(
            '拒绝：目标库 {} 已存在；绝不覆盖。请用 --stage 指定新的唯一名字'.format(stage)
        )

    source_before = counts(SOURCE_DB)
    source_fp_before = schema_fingerprint(SOURCE_DB)

    snapshot = dump_snapshot(credential)
    create_and_restore(stage, credential)

    stage_counts = counts(stage)
    source_after = counts(SOURCE_DB)
    source_fp_after = schema_fingerprint(SOURCE_DB)

    summary = {
        'source_db': SOURCE_DB,
        'source_readonly_user': credential['user'],
        'stage_db': stage,
        'snapshot': snapshot,
        'source_counts_before': source_before,
        'source_counts_after': source_after,
        'source_schema_before': source_fp_before,
        'source_schema_after': source_fp_after,
        'source_unchanged': source_before == source_after
                            and source_fp_before == source_fp_after,
        'stage_counts': stage_counts,
        'counts_match': stage_counts == source_before,
        'stage_schema': schema_fingerprint(stage),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    ok = summary['source_unchanged'] and summary['counts_match']
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
