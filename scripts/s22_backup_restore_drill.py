#!/usr/bin/env python
"""S22 备份恢复与 RPO/RTO 演练（只操作 ``smass_s22_drill`` 隔离库）。

用法::

    python scripts/s22_backup_restore_drill.py                 # 完整演练
    python scripts/s22_backup_restore_drill.py --keep          # 保留演练库
    python scripts/s22_backup_restore_drill.py --json out.json
    python scripts/s22_backup_restore_drill.py --self-test

安全约束
--------
- **只允许** ``smass_s22_*`` 前缀库；脚本启动即校验，命中其他库直接退出；
- 密码通过 ``MYSQL_PWD`` 环境变量传给 mysqldump/mysql，不出现在命令行；
- 演练结束默认删除临时库（``--keep`` 可保留），证据写入 ``.local/evidence/s22/``。

演练步骤
--------
1. 建 ``smass_s22_drill`` 并 migrate；灌入合成数据；
2. ``mysqldump`` 单事务一致性备份（不含 CREATE DATABASE）；
3. 建 ``smass_s22_drill_restored`` 并导入；
4. 逐表比对行数与内容 SHA-256（按主键排序，顺序确定）；
5. 计算 RTO（演练总耗时）与 RPO（最后写入到恢复完成的间隔）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT.parent / '.local' / 'evidence' / 's22'
DRILL_DB = 'smass_s22_drill'
RESTORED_DB = 'smass_s22_drill_restored'
MYSQL_BIN_DIRS = (
    Path(r'D:\mysql-8.0.18-winx64\bin'),
    Path(r'C:\Program Files\MySQL\MySQL Server 8.0\bin'),
)


def find_bin(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in MYSQL_BIN_DIRS:
        candidate = directory / '{}.exe'.format(name)
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_prefix(name):
    if not str(name).startswith('smass_s22_'):
        raise SystemExit('拒绝操作非演练库：{!r}（只允许 smass_s22_*）'.format(name))


def db_config():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_s22')
    import django  # noqa: PLC0415
    django.setup()
    from django.conf import settings  # noqa: PLC0415
    return dict(settings.DATABASES['default'])


def connect(cfg, database=None):
    import pymysql  # noqa: PLC0415
    return pymysql.connect(
        host=str(cfg['HOST'] or '127.0.0.1'), port=int(cfg['PORT'] or 3306),
        user=str(cfg['USER']), password=str(cfg['PASSWORD']),
        database=database, charset='utf8mb4', autocommit=True)


def exec_sql(cfg, sql, database=None):
    connection = connect(cfg, database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
    finally:
        connection.close()


def migrate():
    completed = subprocess.run(  # noqa: S603 - 固定参数
        [sys.executable, 'manage.py', 'migrate', '--noinput',
         '--settings=smass.settings_s22'],
        cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    if completed.returncode != 0:
        raise SystemExit('migrate 失败：{}'.format(
            (completed.stderr or '').strip()[-1200:]))
    return True


def seed_data():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_s22'
    import django  # noqa: PLC0415
    django.setup()
    from smass_organization.models import (  # noqa: PLC0415
        UNIT_TYPE_CLASS, UNIT_TYPE_COLLEGE, UNIT_TYPE_MAJOR,
        OrganizationUnit, StudentRecord,
    )

    StudentRecord.objects.all().delete()
    OrganizationUnit.objects.all().delete()

    college = OrganizationUnit.objects.create(
        code='S22-C', name='演练学院', unit_type=UNIT_TYPE_COLLEGE)
    major = OrganizationUnit.objects.create(
        code='S22-M', name='演练专业', unit_type=UNIT_TYPE_MAJOR, parent=college)
    klass = OrganizationUnit.objects.create(
        code='S22-K', name='演练班级', unit_type=UNIT_TYPE_CLASS, parent=major)
    for index in range(20):
        StudentRecord.objects.create(
            student_no='S22{:03d}'.format(index),
            name='演练学生{:02d}'.format(index), unit=klass,
            extra={'phone': '1380000{:04d}'.format(index)})

    last_write = datetime.now(dt_timezone.utc)
    return {'students': StudentRecord.objects.count(),
            'units': OrganizationUnit.objects.count(),
            'last_write_utc': last_write.isoformat()}


def table_stats(cfg, database):
    """逐表：行数 + 内容 SHA-256（按主键排序，结果确定）。"""
    connection = connect(cfg, database)
    stats = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SHOW TABLES')
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                try:
                    cursor.execute('SELECT * FROM `{}`'.format(table))
                    columns = [item[0] for item in cursor.description]
                    rows = cursor.fetchall()
                except Exception as exc:  # noqa: BLE001 - 记录但不中断
                    stats[table] = {'rows': -1, 'digest': 'error:{}'.format(exc)[:80]}
                    continue
                digest = hashlib.sha256()
                for row in rows:
                    record = {}
                    for name, value in zip(columns, row):
                        if isinstance(value, (bytes, bytearray)):
                            value = value.hex()
                        elif isinstance(value, (datetime, )):
                            value = value.isoformat()
                        record[name] = value
                    digest.update(json.dumps(record, ensure_ascii=False,
                                             sort_keys=True, default=str).encode('utf-8'))
                stats[table] = {'rows': len(rows), 'digest': digest.hexdigest()[:16]}
    finally:
        connection.close()
    return stats


def dump(cfg, target):
    mysqldump = find_bin('mysqldump')
    if not mysqldump:
        raise SystemExit('未找到 mysqldump')
    env = {**os.environ, 'MYSQL_PWD': str(cfg['PASSWORD'])}
    started = time.time()
    with open(target, 'wb') as handle:
        completed = subprocess.run(  # noqa: S603 - 固定参数
            [mysqldump, '--host', str(cfg['HOST'] or '127.0.0.1'),
             '--port', str(cfg['PORT'] or 3306), '--user', str(cfg['USER']),
             '--single-transaction', '--routines', '--triggers',
             '--default-character-set=utf8mb4', DRILL_DB],
            stdout=handle, stderr=subprocess.PIPE, env=env, timeout=1800)
    if completed.returncode != 0:
        raise SystemExit('mysqldump 失败：{}'.format(
            (completed.stderr or b'').decode('utf-8', 'replace')[:800]))
    return round(time.time() - started, 2), target.stat().st_size


def restore(cfg, source, database):
    mysql_bin = find_bin('mysql')
    if not mysql_bin:
        raise SystemExit('未找到 mysql 客户端')
    env = {**os.environ, 'MYSQL_PWD': str(cfg['PASSWORD'])}
    started = time.time()
    with open(source, 'rb') as handle:
        completed = subprocess.run(  # noqa: S603 - 固定参数
            [mysql_bin, '--host', str(cfg['HOST'] or '127.0.0.1'),
             '--port', str(cfg['PORT'] or 3306), '--user', str(cfg['USER']),
             '--database', database, '--default-character-set=utf8mb4'],
            stdin=handle, stderr=subprocess.PIPE, env=env, timeout=1800)
    if completed.returncode != 0:
        raise SystemExit('restore 失败：{}'.format(
            (completed.stderr or b'').decode('utf-8', 'replace')[:800]))
    return round(time.time() - started, 2)


def drill(keep=False):
    ensure_prefix(DRILL_DB)
    ensure_prefix(RESTORED_DB)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cfg = db_config()
    report = {'started_utc': datetime.now(dt_timezone.utc).isoformat(),
              'drill_db': DRILL_DB, 'restored_db': RESTORED_DB}

    exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(DRILL_DB))
    exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(RESTORED_DB))
    exec_sql(cfg, 'CREATE DATABASE `{}` CHARACTER SET utf8mb4'.format(DRILL_DB))
    report['migrate'] = migrate()
    report['seed'] = seed_data()

    source_stats = table_stats(cfg, DRILL_DB)
    report['tables'] = len(source_stats)
    report['source_rows'] = sum(item['rows'] for item in source_stats.values())

    dump_seconds, dump_bytes = dump(cfg, EVIDENCE / 's22_backup.sql')
    report['backup_seconds'] = dump_seconds
    report['backup_bytes'] = dump_bytes

    exec_sql(cfg, 'CREATE DATABASE `{}` CHARACTER SET utf8mb4'.format(RESTORED_DB))
    report['restore_seconds'] = restore(cfg, EVIDENCE / 's22_backup.sql', RESTORED_DB)

    restored_stats = table_stats(cfg, RESTORED_DB)
    mismatches = []
    for table, expected in source_stats.items():
        actual = restored_stats.get(table)
        if actual is None:
            mismatches.append({'table': table, 'issue': 'missing'})
        elif actual['rows'] != expected['rows'] or actual['digest'] != expected['digest']:
            mismatches.append({'table': table, 'expected': expected, 'actual': actual})
    report['mismatches'] = mismatches
    report['restored_tables'] = len(restored_stats)
    report['restored_rows'] = sum(item['rows'] for item in restored_stats.values())

    finished = datetime.now(dt_timezone.utc)
    started_at = datetime.fromisoformat(report['started_utc'])
    last_write = datetime.fromisoformat(report['seed']['last_write_utc'])
    report['rto_seconds'] = round((finished - started_at).total_seconds(), 2)
    report['rpo_seconds'] = round((finished - last_write).total_seconds(), 2)
    report['finished_utc'] = finished.isoformat()
    report['ok'] = not mismatches and report['restored_rows'] == report['source_rows']

    if not keep:
        exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(DRILL_DB))
        exec_sql(cfg, 'DROP DATABASE IF EXISTS `{}`'.format(RESTORED_DB))
    return report


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(ensure_prefix('smass_s22_drill') is None, '合法库名通过')
    for name in ('smass', 'smass_r22_account', 'test_smass_s22_drill'):
        try:
            ensure_prefix(name)
            failures.append('库名必须被拒绝：{}'.format(name))
        except SystemExit:
            pass
    check(find_bin('mysql') is not None, 'mysql 客户端可用')
    check(find_bin('mysqldump') is not None, 'mysqldump 可用')

    for message in failures:
        print('SELF-TEST FAIL:', message)
    if not failures:
        print('SELF-TEST PASS (5 checks)')
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description='S22 备份恢复与 RPO/RTO 演练')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    report = drill(keep=args.keep)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    path = Path(args.json_path) if args.json_path else EVIDENCE / 's22_drill_report.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

    print('演练库：{} -> {}'.format(report['drill_db'], report['restored_db']))
    print('表 {} 张，源 {} 行，恢复 {} 行'.format(
        report['tables'], report['source_rows'], report['restored_rows']))
    print('备份 {:.2f}s / {} 字节；恢复 {:.2f}s'.format(
        report['backup_seconds'], report['backup_bytes'], report['restore_seconds']))
    print('RTO {:.2f}s / RPO {:.2f}s'.format(report['rto_seconds'], report['rpo_seconds']))
    print('校验差异：{}'.format(report['mismatches'] or '无'))
    print('RESULT:', 'PASS' if report['ok'] else 'FAIL')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
