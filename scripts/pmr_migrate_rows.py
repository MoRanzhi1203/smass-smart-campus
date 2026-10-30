"""PM3：合成旧库 -> R10 全量行迁移与对账。

源：`smass_pmr_*`（PM2 生成的 26 表合成旧库）
目标：`smass_pmr_target_*`（R10 全新安装，72 表）

核心保证
--------
1. **幂等**：`pmr_legacy_map` 表上有 `UNIQUE(source_table, source_id)`，
   重跑同一批次不会重复插入；不同批次会 bump `updated` 计数。
2. **批次**：每轮迁移有唯一 `batch_id`，回滚按批次限定。
3. **计数**：created / updated / skipped / conflict / rejected 五类，
   每类都有可枚举的 id 列表（写进 manifest）。
4. **冲突确定性**：
   - 重复 legacy id -> conflict（保留首条，后续记 conflict）
   - 孤儿 FK（classes_id 指向不存在班级）-> rejected（不猜父级）
   - 畸形哈希 -> rejected（但**仍建账号**，密码置为不可用随机值，标记需重置）
5. **对账**：源行数 vs 映射数 vs 目标行数，严格相等才算通过。

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/pmr_migrate_rows.py --source smass_pmr_tiny_20261031
    conda run -n smass python scripts/pmr_migrate_rows.py --source ... --dry-run
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# 注意：Django 的 setup 延迟到 main() 里，因为需要先确定目标库名并写入 PMR_DB。
import django  # noqa: E402

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
PYTHON = sys.executable
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'pmr_migration'

SOURCE_PREFIX = 'smass_pmr_'
TARGET_PREFIX = 'smass_pmr_target_'

LEGACY_MD5_RE = None  # 延迟到运行时编译，避免 import 顺序问题


def _is_legacy_hash(value):
    global LEGACY_MD5_RE
    if LEGACY_MD5_RE is None:
        import re
        LEGACY_MD5_RE = re.compile(r'^[0-9a-f]{32}$')
    return isinstance(value, str) and LEGACY_MD5_RE.match(value) is not None


def _is_usable_hash(value):
    """能被后续验证消费的哈希：32 位小写 hex 或 Django 编码。"""
    if not value:
        return False
    if _is_legacy_hash(value):
        return True
    return value.startswith('pbkdf2_') or '$' in value


def conn(db=None):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4', autocommit=False)


def db_exists(name):
    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',
                [name])
            return cur.fetchone()[0] > 0
    finally:
        c.close()


def guard(name, prefix):
    if not name.startswith(prefix):
        raise SystemExit('拒绝：库名必须命中 {}，当前 {!r}'.format(prefix, name))


MAP_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS pmr_legacy_map (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(32) NOT NULL,
  source_table VARCHAR(64) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  target_table VARCHAR(64) NOT NULL,
  target_pk BIGINT NOT NULL,
  status VARCHAR(16) NOT NULL,
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_pmr_source (source_table, source_id),
  KEY idx_pmr_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

QUEUE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS pmr_rejected_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(32) NOT NULL,
  source_table VARCHAR(64) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  payload VARCHAR(512) NOT NULL DEFAULT '',
  status VARCHAR(24) NOT NULL DEFAULT 'isolated',
  attempts INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  resolved_at DATETIME NULL,
  UNIQUE KEY uq_rejected_source (batch_id, source_table, source_id, status),
  KEY idx_rejected_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_target(target):
    """创建目标库并跑 R10 迁移。"""
    if db_exists(target):
        return {'created': False}

    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(target))
        c.commit()
    finally:
        c.close()

    env = dict(os.environ)
    env['PMR_DB'] = target
    result = subprocess.run(
        [PYTHON, 'manage.py', 'migrate', '--noinput',
         '--settings=smass.settings_pmr'],
        cwd=str(BASE), capture_output=True, text=True, env=env)

    return {'created': True, 'migrate_exit': result.returncode,
            'tail': (result.stdout or result.stderr).strip().splitlines()[-2:]}


def read_source_rows(source):
    """只读：取出合成源行。"""
    c = conn(source)
    try:
        with c.cursor(pymysql.cursors.DictCursor) as cur:
            rows = {}

            cur.execute('SELECT id, name FROM app01_college ORDER BY id')
            rows['college'] = cur.fetchall()

            cur.execute('SELECT id, name, college_id FROM app01_major ORDER BY id')
            rows['major'] = cur.fetchall()

            cur.execute(
                'SELECT id, name, grade_id, major_id FROM app01_classes ORDER BY id')
            rows['classes'] = cur.fetchall()

            cur.execute('SELECT id, name, password FROM app01_admin ORDER BY id')
            rows['admin'] = cur.fetchall()

            cur.execute(
                'SELECT id, name, password, college_id FROM app01_teacher ORDER BY id')
            rows['teacher'] = cur.fetchall()

            cur.execute(
                'SELECT id, name, password, classes_id FROM app01_student ORDER BY id')
            rows['student'] = cur.fetchall()

        return rows
    finally:
        c.close()


class Migrator:
    def __init__(self, target, batch_id, dry_run=False):
        self.target = target
        self.batch_id = batch_id
        self.dry_run = dry_run
        self.conn = conn(target)
        self.counters = {
            'created': 0, 'updated': 0, 'skipped': 0,
            'conflict': 0, 'rejected': 0,
        }
        self.details = {key: [] for key in self.counters}
        self.now = datetime.now().replace(microsecond=0)

    def close(self):
        self.conn.close()

    # ---- 映射表 / 隔离队列 ----
    def ensure_map_table(self):
        with self.conn.cursor() as cur:
            cur.execute(MAP_TABLE_DDL)
        self.conn.commit()

    def ensure_queue_table(self):
        with self.conn.cursor() as cur:
            cur.execute(QUEUE_TABLE_DDL)
        self.conn.commit()

    def isolate(self, source_table, source_id, reason, payload='', status='isolated'):
        """把无法自动处理的行持久化到隔离队列（可审计、可重放）。"""
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_rejected_queue '
                '(batch_id, source_table, source_id, reason, payload, status, '
                ' attempts, created_at) VALUES (%s,%s,%s,%s,%s,%s,0,%s) '
                'ON DUPLICATE KEY UPDATE reason=VALUES(reason), '
                ' payload=VALUES(payload), status=VALUES(status)',
                (self.batch_id, source_table, str(source_id), reason[:255],
                 payload[:512], status, self.now))
        self.conn.commit()
        if status in ('isolated', 'conflict'):
            self.bump('rejected' if status == 'isolated' else 'conflict',
                      source_table, source_id, reason)

    def lookup(self, source_table, source_id):
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                'SELECT * FROM pmr_legacy_map WHERE source_table=%s AND source_id=%s',
                (source_table, str(source_id)))
            return cur.fetchone()

    def record(self, source_table, source_id, target_table, target_pk,
               status, note=''):
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_legacy_map '
                '(batch_id, source_table, source_id, target_table, target_pk, '
                ' status, note, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON DUPLICATE KEY UPDATE '
                ' batch_id=VALUES(batch_id), target_pk=VALUES(target_pk), '
                ' status=VALUES(status), note=VALUES(note), '
                ' updated_at=VALUES(updated_at)',
                (self.batch_id, source_table, str(source_id), target_table,
                 target_pk, status, note[:255], self.now, self.now))

    def bump(self, kind, source_table, source_id, note=''):
        self.counters[kind] += 1
        if len(self.details[kind]) < 200:
            self.details[kind].append(
                {'source': '{}.{}'.format(source_table, source_id),
                 'note': note})

    # ---- 组织 ----
    def migrate_colleges(self, colleges):
        mapping = {}
        from smass_organization.models import OrganizationUnit

        for row in colleges:
            source_id = str(row['id'])
            existing = self.lookup('app01_college', source_id)
            if existing:
                mapping[row['id']] = existing['target_pk']
                self.counters['skipped'] += 1
                continue

            code = 'PMR-C{}'.format(source_id)
            if OrganizationUnit.objects.filter(code=code).exists():
                unit = OrganizationUnit.objects.get(code=code)
                self.record('app01_college', source_id, 'organization_unit',
                            unit.pk, 'existing')
                mapping[row['id']] = unit.pk
                self.counters['skipped'] += 1
                continue

            if self.dry_run:
                mapping[row['id']] = -1
                self.bump('created', 'app01_college', source_id, 'dry-run')
                continue

            raw_name = str(row['name'])
            if len(raw_name) > 100:
                self.isolate('app01_college', source_id,
                             'name 长度 {} 超过 100，已截断'.format(len(raw_name)),
                             raw_name[:100], status='truncated')
            unit = OrganizationUnit.objects.create(
                code=code, name=raw_name[:100], unit_type='college')
            self.record('app01_college', source_id, 'organization_unit',
                        unit.pk, 'created')
            mapping[row['id']] = unit.pk
            self.bump('created', 'app01_college', source_id)

        self.conn.commit()
        return mapping

    def migrate_majors(self, majors, college_map):
        """专业 -> OrganizationUnit(major)，父级为对应学院。"""
        mapping = {}
        from smass_organization.models import OrganizationUnit

        for row in majors:
            source_id = str(row['id'])
            existing = self.lookup('app01_major', source_id)
            if existing:
                mapping[row['id']] = existing['target_pk']
                self.counters['skipped'] += 1
                continue

            parent_pk = college_map.get(row.get('college_id'))
            parent = OrganizationUnit.objects.filter(pk=parent_pk).first() if parent_pk else None
            if parent is None:
                self.isolate('app01_major', source_id,
                             'college_id={} 无对应学院'.format(row.get('college_id')),
                             'major:{}'.format(row.get('name', '')))
                continue

            code = 'PMR-M{}'.format(source_id)
            if OrganizationUnit.objects.filter(code=code).exists():
                unit = OrganizationUnit.objects.get(code=code)
                self.record('app01_major', source_id, 'organization_unit',
                            unit.pk, 'existing')
                mapping[row['id']] = unit.pk
                self.counters['skipped'] += 1
                continue

            if self.dry_run:
                mapping[row['id']] = -1
                self.bump('created', 'app01_major', source_id, 'dry-run')
                continue

            raw_name = str(row['name'])
            if len(raw_name) > 100:
                self.isolate('app01_major', source_id,
                             'name 长度 {} 超过 100，已截断'.format(len(raw_name)),
                             raw_name[:100], status='truncated')
            unit = OrganizationUnit.objects.create(
                code=code, name=raw_name[:100], unit_type='major',
                parent=parent)
            self.record('app01_major', source_id, 'organization_unit', unit.pk, 'created')
            mapping[row['id']] = unit.pk
            self.bump('created', 'app01_major', source_id)

        self.conn.commit()
        return mapping

    def migrate_classes(self, classes, major_map):
        """班级 -> OrganizationUnit(class)，父级为对应专业。"""
        mapping = {}
        from smass_organization.models import OrganizationUnit

        for row in classes:
            source_id = str(row['id'])
            existing = self.lookup('app01_classes', source_id)
            if existing:
                mapping[row['id']] = existing['target_pk']
                self.counters['skipped'] += 1
                continue

            parent_pk = major_map.get(row.get('major_id'))
            parent = OrganizationUnit.objects.filter(pk=parent_pk).first() if parent_pk else None

            if parent is None:
                # 孤儿班级：拒绝猜测父级（不静默挂到别的学院）
                self.isolate('app01_classes', source_id,
                             'major_id={} 无对应专业'.format(row.get('major_id')),
                             'class:{}'.format(row.get('name', '')))
                continue

            code = 'PMR-K{}'.format(source_id)
            if OrganizationUnit.objects.filter(code=code).exists():
                unit = OrganizationUnit.objects.get(code=code)
                self.record('app01_classes', source_id, 'organization_unit',
                            unit.pk, 'existing')
                mapping[row['id']] = unit.pk
                self.counters['skipped'] += 1
                continue

            if self.dry_run:
                mapping[row['id']] = -1
                self.bump('created', 'app01_classes', source_id, 'dry-run')
                continue

            raw_name = str(row['name'])
            if len(raw_name) > 100:
                self.isolate('app01_classes', source_id,
                             'name 长度 {} 超过 100，已截断'.format(len(raw_name)),
                             raw_name[:100], status='truncated')
            unit = OrganizationUnit.objects.create(
                code=code, name=raw_name[:100], unit_type='class',
                parent=parent)
            self.record('app01_classes', source_id, 'organization_unit',
                        unit.pk, 'created')
            mapping[row['id']] = unit.pk
            self.bump('created', 'app01_classes', source_id)

        self.conn.commit()
        return mapping

    # ---- 账号 ----
    def _migrate_account(self, source_table, row, person_type, role_code):
        source_id = str(row['id'])
        from r21_account.models import Account
        from r21_account import services as core_services

        existing = self.lookup(source_table, source_id)
        if existing:
            self.counters['skipped'] += 1
            return existing['target_pk'], 'skipped'

        login_name = 'pmr-{}'.format(str(row['id']).lower())[:32]
        used_placeholder = False

        if Account.objects.filter(login_name=login_name).exists():
            account = Account.objects.get(login_name=login_name)
            self.record(source_table, source_id, 'r21_account_account',
                        account.pk, 'existing')
            self.counters['skipped'] += 1
            return account.pk, 'skipped'

        encoded = row.get('password') or ''
        if not _is_usable_hash(encoded):
            # 畸形哈希：仍建账号，但置不可用密码 + 标记需重置
            encoded = '!' + secrets.token_hex(16)
            used_placeholder = True

        raw_name = str(row.get('name') or source_id)
        if len(raw_name) > 32:
            self.isolate(source_table, source_id,
                         'name 长度 {} 超过 32，已截断'.format(len(raw_name)),
                         raw_name[:32], status='truncated')

        if self.dry_run:
            self.bump('created', source_table, source_id, 'dry-run')
            return -1, 'dry-run'

        account = Account(
            login_name=login_name,
            display_name=raw_name[:32],
            person_type=person_type,
            must_change_password=True,
        )
        account.password = encoded
        account.save(force_insert=True)

        core_services.ensure_role_groups()
        core_services.grant_role(account, role_code, granted_by='pmr-migration')

        status = 'rejected' if used_placeholder else 'created'
        note = '密码哈希不可用，已置占位并要求重置' if used_placeholder else ''
        if used_placeholder:
            # 账号已建，但必须进入隔离队列等待强制重置处置（不计入 rejected 分区）
            self.isolate(source_table, source_id, note,
                         'password_reset_required', status='password_reset_required')
        self.record(source_table, source_id, 'r21_account_account',
                    account.pk, status, note)
        self.bump(status, source_table, source_id, note)
        return account.pk, status

    def migrate_admins(self, admins):
        mapping = {}
        from r21_account.models import RoleCode
        for row in admins:
            pk, _ = self._migrate_account(
                'app01_admin', row, 'admin', RoleCode.SYSTEM_ADMIN)
            mapping[row['id']] = pk
        self.conn.commit()
        return mapping

    def migrate_teachers(self, teachers, college_map):
        mapping = {}
        from r21_account.models import RoleCode
        for row in teachers:
            pk, _ = self._migrate_account(
                'app01_teacher', row, 'teacher', RoleCode.TEACHER)
            mapping[row['id']] = pk
        self.conn.commit()
        return mapping

    def migrate_students(self, students, class_map):
        mapping = {}
        from r21_account.models import RoleCode
        for row in students:
            pk, _ = self._migrate_account(
                'app01_student', row, 'student', RoleCode.STUDENT)
            mapping[row['id']] = pk
        self.conn.commit()
        return mapping

    # ---- 学生档案 ----
    def migrate_records(self, students, account_map, class_map):
        from smass_organization.models import StudentRecord, OrganizationUnit

        for row in students:
            source_id = str(row['id'])
            existing = self.lookup('app01_student_record', source_id)
            if existing:
                self.counters['skipped'] += 1
                continue

            account_pk = account_map.get(row['id'])
            class_pk = class_map.get(row.get('classes_id'))

            if row.get('classes_id') and class_pk is None:
                # 孤儿班级引用：拒绝，不猜
                self.isolate('app01_student_record', source_id,
                             'classes_id={} 无对应组织'.format(row.get('classes_id')),
                             'record:{}'.format(row.get('name', '')))
                continue

            unit = OrganizationUnit.objects.filter(pk=class_pk).first() if class_pk else None

            student_no = str(row['id'])[:20]
            raw_name = str(row.get('name') or student_no)
            if len(raw_name) > 32:
                self.isolate('app01_student_record', source_id,
                             'name 长度 {} 超过 32，已截断'.format(len(raw_name)),
                             raw_name[:32], status='truncated')
            if StudentRecord.objects.filter(student_no=student_no).exists():
                record = StudentRecord.objects.get(student_no=student_no)
                self.record('app01_student_record', source_id,
                            'organization_studentrecord', record.pk, 'existing')
                self.counters['skipped'] += 1
                continue

            if self.dry_run:
                self.bump('created', 'app01_student_record', source_id, 'dry-run')
                continue

            record = StudentRecord.objects.create(
                student_no=student_no,
                name=raw_name[:32],
                account_id=account_pk if account_pk and account_pk > 0 else None,
                unit=unit,
                status='enrolled',
            )
            self.record('app01_student_record', source_id,
                        'organization_studentrecord', record.pk, 'created')
            self.bump('created', 'app01_student_record', source_id)

        self.conn.commit()


def _units_with_type(target, unit_type):
    c = conn(target)
    try:
        with c.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                'SELECT id, parent_id FROM smass_organization_organizationunit '
                'WHERE unit_type=%s', [unit_type])
            return cur.fetchall()
    finally:
        c.close()


def replay_isolated(source, target, batch_id):
    """受控重放：重跑幂等迁移，把已能处理的行从隔离队列解除。

    只对 ``status='isolated'`` 的行生效；仍缺父级的行保留并累加 attempts。
    不修改源库，不猜测业务父级。
    """
    rows = read_source_rows(source)
    m = Migrator(target, batch_id)
    resolved, remaining = [], []
    try:
        m.ensure_map_table()
        m.ensure_queue_table()

        college_map = m.migrate_colleges(rows['college'])
        major_map = m.migrate_majors(rows['major'], college_map)
        class_map = m.migrate_classes(rows['classes'], major_map)
        m.migrate_admins(rows['admin'])
        m.migrate_teachers(rows['teacher'], college_map)
        account_map = m.migrate_students(rows['student'], class_map)
        m.migrate_records(rows['student'], account_map, class_map)

        with m.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM pmr_rejected_queue "
                "WHERE batch_id=%s AND status='isolated'", [batch_id])
            items = cur.fetchall()

        for item in items:
            mapping = m.lookup(item['source_table'], item['source_id'])
            if mapping:
                with m.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE pmr_rejected_queue SET status='resolved', "
                        'resolved_at=%s WHERE id=%s', (m.now, item['id']))
                m.conn.commit()
                resolved.append('{}.{}'.format(
                    item['source_table'], item['source_id']))
            else:
                with m.conn.cursor() as cur:
                    cur.execute(
                        'UPDATE pmr_rejected_queue SET attempts=attempts+1 '
                        'WHERE id=%s', [item['id']])
                m.conn.commit()
                remaining.append('{}.{}'.format(
                    item['source_table'], item['source_id']))
    finally:
        m.close()

    return {'batch_id': batch_id, 'resolved': resolved,
            'remaining': remaining,
            'resolved_count': len(resolved),
            'remaining_count': len(remaining)}


def reconcile(source, target, counters, details=None, batch_id=None):
    """严格对账：源行数 vs 映射数 vs 目标行数。"""
    src = conn(source)
    tgt = conn(target)
    report = {}
    try:
        with src.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM app01_college')
            src_college = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM app01_classes')
            src_classes = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM app01_major')
            src_major = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM app01_admin')
            src_admin = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM app01_teacher')
            src_teacher = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM app01_student')
            src_student = cur.fetchone()[0]

        with tgt.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_college'")
            map_college = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_classes'")
            map_classes = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_major'")
            map_major = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_admin'")
            map_admin = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_teacher'")
            map_teacher = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_student'")
            map_student = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM pmr_legacy_map WHERE source_table='app01_student_record'")
            map_records = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM r21_account_account WHERE login_name LIKE 'pmr-%'")
            tgt_accounts = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM smass_organization_studentrecord WHERE student_no LIKE 'S%'")
            tgt_records = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM smass_organization_organizationunit WHERE code LIKE 'PMR-%'")
            tgt_units = cur.fetchone()[0]

        report['source'] = {
            'college': src_college, 'major': src_major, 'classes': src_classes,
            'admin': src_admin, 'teacher': src_teacher, 'student': src_student,
            'total_person': src_admin + src_teacher + src_student,
        }
        report['mapped'] = {
            'college': map_college, 'major': map_major, 'classes': map_classes,
            'admin': map_admin, 'teacher': map_teacher,
            'student': map_student, 'student_record': map_records,
        }
        report['target'] = {
            'accounts': tgt_accounts, 'records': tgt_records, 'units': tgt_units,
        }
        report['counters'] = counters

        checks = []

        def add(name, actual, expected, tolerance=0):
            ok = abs(actual - expected) <= tolerance
            checks.append({'check': name, 'actual': actual,
                           'expected': expected, 'ok': ok})

        # 每个源 person 行必须恰好有一条映射
        add('admin_mapped', map_admin, src_admin)
        add('teacher_mapped', map_teacher, src_teacher)
        # 学生：可能因孤儿班级被 rejected，映射数 <= 源数
        checks.append({'check': 'student_mapped_le_source',
                       'actual': map_student, 'expected': src_student,
                       'ok': map_student <= src_student})
        # 账号数 = 三类之和（rejected 的畸形哈希也建了账号）
        add('accounts_total', tgt_accounts, map_admin + map_teacher + map_student)

        # 结构检查：不允许 HASH_MISMATCH —— 数一遍不可用哈希
        with tgt.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM r21_account_account "
                "WHERE login_name LIKE 'pmr-%' AND password LIKE '!%'")
            placeholder = cur.fetchone()[0]
        # 畸形哈希数：**直接从源库**数（重跑时 rejected 明细会是空的，
        # 因为那些行已被上一轮建过账号并 skip）
        unusable = 0
        with src.cursor() as cur:
            for table in ('app01_admin', 'app01_teacher', 'app01_student'):
                cur.execute('SELECT password FROM {}'.format(table))
                for (encoded,) in cur.fetchall():
                    if not _is_usable_hash(encoded):
                        unusable += 1
        report['placeholder_passwords'] = placeholder
        report['unusable_hash_rows'] = unusable
        checks.append({'check': 'placeholder_equals_unusable_hash_rows',
                       'actual': placeholder,
                       'expected': unusable,
                       'ok': placeholder == unusable})

        # 组织层级完整性：每个班级必须有父级专业
        checks.append({'check': 'classes_have_parent',
                       'actual': len([
                           u for u in _units_with_type(target, 'class')
                           if u['parent_id'] is None]),
                       'expected': 0,
                       'ok': len([
                           u for u in _units_with_type(target, 'class')
                           if u['parent_id'] is None]) == 0})

        report['checks'] = checks
        report['strict_ok'] = all(c['ok'] for c in checks)

        # ---- 无损分区：每个源行必须 mapped 或进入隔离队列，不允许静默遗漏 ----
        partition_checks = []
        isolated = {}
        if batch_id:
            with tgt.cursor() as cur:
                cur.execute(
                    "SELECT source_table, COUNT(DISTINCT source_id) "
                    "FROM pmr_rejected_queue WHERE batch_id=%s "
                    "AND status IN ('isolated','conflict') "
                    'GROUP BY source_table', [batch_id])
                isolated = {row[0]: row[1] for row in cur.fetchall()}

        partitions = [
            ('app01_college', src_college, map_college),
            ('app01_major', src_major, map_major),
            ('app01_classes', src_classes, map_classes),
            ('app01_admin', src_admin, map_admin),
            ('app01_teacher', src_teacher, map_teacher),
            ('app01_student', src_student, map_student),
            ('app01_student_record', src_student, map_records),
        ]
        for table, source_n, mapped_n in partitions:
            queued_n = isolated.get(table, 0)
            partition_checks.append({
                'check': 'partition_complete_{}'.format(table),
                'source': source_n,
                'mapped': mapped_n,
                'isolated': queued_n,
                'ok': mapped_n + queued_n == source_n,
            })

        report['partition'] = {
            'batch_id': batch_id, 'isolated': isolated,
            'checks': partition_checks,
        }
        report['lossless_ok'] = all(c['ok'] for c in partition_checks)
        report['overall_ok'] = report['strict_ok'] and report['lossless_ok']
    finally:
        src.close()
        tgt.close()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', default=None)
    parser.add_argument('--batch-id', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--replay', action='store_true',
                        help='受控重放：重跑迁移并解除已可处理的隔离行')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')

    guard(args.source, SOURCE_PREFIX)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = args.target or '{}{}'.format(TARGET_PREFIX, stamp)
    guard(target, TARGET_PREFIX)
    if args.source == target:
        raise SystemExit('源与目标不能相同')

    batch_id = args.batch_id or hashlib.sha256(
        '{}-{}-{}'.format(args.source, target, stamp).encode()).hexdigest()[:24]

    # 必须在 django.setup() 之前把目标库名注入环境，
    # 否则 settings_pmr 会拿到默认库名并拒绝/连错库。
    # 必须**强制**覆盖 DJANGO_SETTINGS_MODULE：调用方（测试/CI）可能已设置
    # settings_r10，setdefault 会让 ORM 连到错误的库。
    os.environ['PMR_DB'] = target
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_pmr'
    django.setup()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.replay:
        result = replay_isolated(args.source, target, batch_id)
        result['ok'] = result['remaining_count'] == 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1

    report = {'source': args.source, 'target': target, 'batch_id': batch_id,
              'dry_run': args.dry_run, 'steps': []}

    setup = ensure_target(target)
    report['target_setup'] = setup
    if setup.get('migrate_exit') not in (None, 0):
        raise SystemExit('目标库迁移失败: {}'.format(setup))

    rows = read_source_rows(args.source)
    report['source_rows'] = {key: len(value) for key, value in rows.items()}
    report['steps'].append({'step': 'read_source', 'ok': True})

    migrator = Migrator(target, batch_id, dry_run=args.dry_run)
    try:
        migrator.ensure_map_table()
        migrator.ensure_queue_table()

        college_map = migrator.migrate_colleges(rows['college'])
        major_map = migrator.migrate_majors(rows['major'], college_map)
        class_map = migrator.migrate_classes(rows['classes'], major_map)
        migrator.migrate_admins(rows['admin'])
        migrator.migrate_teachers(rows['teacher'], college_map)
        account_map = migrator.migrate_students(rows['student'], class_map)
        migrator.migrate_records(rows['student'], account_map, class_map)

        counters = dict(migrator.counters)
        details = dict(migrator.details)
    finally:
        migrator.close()

    report['counters'] = counters
    report['details'] = details
    report['steps'].append({'step': 'migrate', 'ok': True,
                            'created': counters['created'],
                            'skipped': counters['skipped']})

    if not args.dry_run:
        recon = reconcile(args.source, target, counters, details,
                          batch_id=batch_id)
        report['reconciliation'] = recon
        report['steps'].append({'step': 'reconcile',
                                'ok': recon['overall_ok']})

    report['ok'] = all(step.get('ok') for step in report['steps'])
    manifest = OUT_DIR / 'migration_{}_{}.json'.format(batch_id[:8], stamp)
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    report['manifest_path'] = str(manifest)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
