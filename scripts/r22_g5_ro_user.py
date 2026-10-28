"""G5.0：建立并验证**数据库级只读**访问（只增，不改动现有授权）。

安全边界：
- 只对 ``smass`` 授予 ``SELECT``；不授予任何写权限；
- 不修改、不回收任何既有账号的权限；
- 生成的凭据只写入本机临时文件（不在仓库内），报告只引用用户名与验证结论。

验证方法（证明"不是仅应用层检查"）：
1. 用只读账号 ``SELECT`` 成功；
2. 用只读账号执行 ``UPDATE`` / ``INSERT`` / ``DELETE`` / ``CREATE TABLE``，**必须被数据库拒绝**。

用法：
    conda run -n smass python scripts/r22_g5_ro_user.py
"""
import json
import os
import secrets
import sys
from pathlib import Path

import pymysql

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
SOURCE_DB = 'smass'
RO_USER = 'smass_g5_ro'

CRED_FILE = Path(os.environ.get('TEMP', '.')) / 'smass_g5_ro_credential.txt'


def admin_conn():
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD)


def ensure_readonly_user():
    password = secrets.token_urlsafe(24)

    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host=%s",
                [RO_USER, HOST],
            )
            exists = cur.fetchone()[0] > 0

            # 必须显式指定 mysql_native_password：MySQL 8 默认 caching_sha2_password，
            # PyMySQL 在无 cryptography 包时无法完成该认证。
            if exists:
                cur.execute(
                    "ALTER USER '{}'@'{}' IDENTIFIED WITH mysql_native_password BY '{}'".format(
                        RO_USER, HOST, password
                    )
                )
            else:
                cur.execute(
                    "CREATE USER '{}'@'{}' IDENTIFIED WITH mysql_native_password BY '{}'".format(
                        RO_USER, HOST, password
                    )
                )

            # 只授予 SELECT（幂等）
            cur.execute(
                "GRANT SELECT ON `{}`.* TO '{}'@'{}'".format(SOURCE_DB, RO_USER, HOST)
            )
            cur.execute("FLUSH PRIVILEGES")
        conn.commit()
    finally:
        conn.close()

    CRED_FILE.write_text(
        json.dumps({'user': RO_USER, 'host': HOST, 'password': password, 'db': SOURCE_DB}),
        encoding='utf-8',
    )
    return password


def verify_grants():
    conn = admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW GRANTS FOR '{}'@'{}'".format(RO_USER, HOST))
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def verify_readonly_enforced(password):
    """用只读账号尝试各类写操作，全部应被数据库拒绝。"""
    results = {}

    conn = pymysql.connect(host=HOST, user=RO_USER, password=password, database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM app01_student')
            results['select_ok'] = cur.fetchone()[0] >= 0

            write_probes = {
                'update': 'UPDATE app01_student SET name = name WHERE 1=0',
                'insert': "INSERT INTO app01_admin (id, name) VALUES ('__probe__', 'probe')",
                'delete': 'DELETE FROM app01_student WHERE 1=0',
                'create': 'CREATE TABLE __ro_probe (id INT)',
            }

            for name, sql in write_probes.items():
                try:
                    cur.execute(sql)
                    conn.commit()
                    results[name] = {'denied': False, 'error': None}
                except Exception as exc:  # noqa: BLE001
                    results[name] = {'denied': True, 'error': type(exc).__name__}
                    conn.rollback()
    finally:
        conn.close()

    return results


def main():
    password = ensure_readonly_user()
    grants = verify_grants()
    probes = verify_readonly_enforced(password)

    write_denied = all(
        probes[k]['denied'] for k in ('update', 'insert', 'delete', 'create')
    )

    summary = {
        'readonly_user': RO_USER,
        'credential_file': str(CRED_FILE),
        'grants': grants,
        'select_ok': probes['select_ok'],
        'write_probes': probes,
        'database_level_readonly_enforced': write_denied,
        'credential_in_repo': False,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if (probes['select_ok'] and write_denied) else 1


if __name__ == '__main__':
    raise SystemExit(main())
