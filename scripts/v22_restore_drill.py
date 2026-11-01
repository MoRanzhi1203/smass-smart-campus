"""V2.2 恢复演练（隔离验证库，不触碰 smass_campus）。"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql

from smass.env_loader import load_env

load_env(ROOT / '.env')

RESTORE_DB = 'smass_campus_restore_check'
backup_dir = ROOT / '.local/backup'
backups = sorted(backup_dir.glob('smass_campus_*.sql'))
if not backups:
    print('NO_BACKUP')
    raise SystemExit(1)
backup = backups[-1]
print('backup', backup.name, round(backup.stat().st_size / 1048576, 1), 'MB')

host = os.environ.get('DB_HOST', '127.0.0.1')
port = os.environ.get('DB_PORT', '3306')
user = os.environ.get('DB_USER', 'root')
password = os.environ.get('DB_PASSWORD', '')

conn = pymysql.connect(host=host, port=int(port), user=user,
                       password=password, charset='utf8mb4')
with conn.cursor() as cursor:
    cursor.execute('SHOW DATABASES LIKE %s', [RESTORE_DB])
    if cursor.fetchone():
        print('STOP: 演练库已存在，先人工核对')
        conn.close()
        raise SystemExit(2)
    cursor.execute(
        'CREATE DATABASE {} CHARACTER SET utf8mb4 '
        'COLLATE utf8mb4_unicode_ci'.format(RESTORE_DB))
print('created', RESTORE_DB)

env = dict(os.environ)
env['MYSQL_PWD'] = password
started = time.perf_counter()
with open(backup, 'rb') as handle:
    result = subprocess.run(
        ['mysql', '--host', host, '--port', port, '--user', user,
         '--default-character-set=utf8mb4', RESTORE_DB],
        stdin=handle, stderr=subprocess.PIPE, env=env)
print('restore_rc', result.returncode, 'seconds',
      round(time.perf_counter() - started, 1))
if result.returncode != 0:
    print('stderr', result.stderr.decode('utf-8', 'ignore')[:400])

conn = pymysql.connect(host=host, port=int(port), user=user,
                       password=password, charset='utf8mb4',
                       database=RESTORE_DB)
with conn.cursor() as cursor:
    cursor.execute(
        'SELECT COUNT(1) FROM information_schema.tables '
        'WHERE table_schema=%s', [RESTORE_DB])
    print('tables', cursor.fetchone()[0])
    cursor.execute('SELECT COUNT(1) FROM smass_organization_studentrecord')
    print('students', cursor.fetchone()[0])
    cursor.execute('SELECT COUNT(1) FROM smass_academic_enrollment')
    print('enrollments', cursor.fetchone()[0])
    cursor.execute('SELECT COUNT(1) FROM smass_dormitory_dormassignment '
                   'WHERE active_slot = 1')
    print('dorm_active', cursor.fetchone()[0])
conn.close()

# 演练库用后即删（非业务库）
conn = pymysql.connect(host=host, port=int(port), user=user,
                       password=password, charset='utf8mb4')
with conn.cursor() as cursor:
    cursor.execute('DROP DATABASE {}'.format(RESTORE_DB))
print('dropped', RESTORE_DB)
conn.close()
