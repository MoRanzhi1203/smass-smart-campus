#!/usr/bin/env python
"""SMASS 统一数据库验证环境：初始化、迁移、种子、校验、回滚。

    python scripts/db_unify.py init       # 重建验证库并迁移
    python scripts/db_unify.py migrate    # 只执行迁移
    python scripts/db_unify.py seed       # 幂等写入基础配置与合成数据
    python scripts/db_unify.py verify     # 结构/约束/外键/数据校验
    python scripts/db_unify.py rollback   # 删除验证库（仅前缀允许）
    python scripts/db_unify.py plan       # 输出迁移计划

安全：只操作 ``smass_unified_verify`` 前缀库；不连接、不写入正式库 ``smass``。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SETTINGS = 'smass.settings_unified_verify'
DB_NAME = os.environ.get('UNIFIED_DB', 'smass_unified_verify')
ALLOWED_PREFIX = 'smass_unified_verify'


def guard():
    if not DB_NAME.startswith(ALLOWED_PREFIX):
        raise SystemExit('拒绝操作非验证库：{!r}'.format(DB_NAME))
    if DB_NAME in ('smass', 'smass_product_dev'):
        raise SystemExit('拒绝操作正式库或产品开发库：{!r}'.format(DB_NAME))


def setup():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.conf import settings

    return settings


def admin_connection():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    import pymysql

    return pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        charset='utf8mb4', autocommit=True)


def database_exists(name):
    connection = admin_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s',
                (name,))
            return cursor.fetchone()[0] > 0
    finally:
        connection.close()


def create_database(recreate=False):
    connection = admin_connection()
    try:
        with connection.cursor() as cursor:
            if recreate:
                cursor.execute('DROP DATABASE IF EXISTS `{}`'.format(DB_NAME))
            cursor.execute(
                'CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4'.format(
                    DB_NAME))
    finally:
        connection.close()


def drop_database():
    guard()
    connection = admin_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE IF EXISTS `{}`'.format(DB_NAME))
    finally:
        connection.close()


def run_migrate():
    completed = subprocess.run(
        [sys.executable, 'manage.py', 'migrate', '--noinput',
         '--settings={}'.format(SETTINGS)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=3600)
    if completed.returncode != 0:
        raise SystemExit('migrate 失败：{}'.format(
            (completed.stderr or '').strip()[-2000:]))
    return completed.stdout


def run_plan():
    completed = subprocess.run(
        [sys.executable, 'manage.py', 'showmigrations', '--plan',
         '--settings={}'.format(SETTINGS)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=600)
    return completed.stdout


def seed():
    from datetime import date

    from r21_account import services as account_services
    from r21_account.models import Account, StudentProfile, TeacherProfile
    from smass_academic.models import AcademicTerm, AcademicYear, Course, TeachingSection
    from smass_organization.models import OrganizationUnit, StudentRecord
    from smass_organization.services import create_unit

    account_services.ensure_role_groups()

    college = OrganizationUnit.objects.filter(code='UNI-COL').first() or create_unit(
        code='UNI-COL', name='统一验证学院', unit_type='college')
    major = OrganizationUnit.objects.filter(code='UNI-MAJ').first() or create_unit(
        code='UNI-MAJ', name='验证专业', unit_type='major', parent=college)
    klass = OrganizationUnit.objects.filter(code='UNI-CLS').first() or create_unit(
        code='UNI-CLS', name='验证2401', unit_type='class', parent=major)
    department = OrganizationUnit.objects.filter(code='UNI-DEPT').first() or create_unit(
        code='UNI-DEPT', name='验证部门', unit_type='department')

    password = os.environ.get('UNIFIED_SEED_PASSWORD') or 'Unified-Dev-2026'
    people = (
        ('uni_admin', '验证管理员', 'admin', ('system_admin',)),
        ('uni_teacher', '验证教师', 'teacher', ('teacher',)),
        ('uni_student', '验证学生', 'student', ('student',)),
    )
    for login_name, display, person_type, roles in people:
        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            account = Account.objects.create_user(
                login_name, password, display_name=display,
                person_type=person_type)
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        for role in roles:
            account_services.grant_role(account, role, granted_by='db-unify-seed')

    student = Account.objects.get(login_name='uni_student')
    StudentProfile.objects.update_or_create(
        account=student,
        defaults={'student_no': 'UNI2024001', 'name': '验证学生',
                  'college_name': '统一验证学院', 'classes_name': '验证2401'})
    StudentRecord.objects.update_or_create(
        student_no='UNI2024001',
        defaults={'name': '验证学生', 'account': student, 'unit': klass,
                  'status': 'enrolled', 'enrolled_at': date(2024, 9, 1),
                  'extra': {'dormitory': {'building': '验证公寓',
                                          'room': '101', 'bed': '1 号床'}}})
    teacher = Account.objects.get(login_name='uni_teacher')
    TeacherProfile.objects.update_or_create(
        account=teacher,
        defaults={'teacher_no': 'UNIT001', 'name': '验证教师',
                  'college_name': '统一验证学院'})

    year = AcademicYear.objects.filter(code='UNI-2024').first()
    if year is None:
        year = AcademicYear.objects.create(
            code='UNI-2024', start_date=date(2024, 9, 1),
            end_date=date(2025, 8, 31), is_active=True)
    term = AcademicTerm.objects.filter(year=year, semester='1').first()
    if term is None:
        term = AcademicTerm.objects.create(
            year=year, semester='1', name='2024-2025-1',
            start_date=date(2024, 9, 1), end_date=date(2025, 1, 15),
            is_active=True)
    course = Course.objects.filter(code='UNI-CS101').first()
    if course is None:
        course = Course.objects.create(
            code='UNI-CS101', title='验证课程', credit=3)
    TeachingSection.objects.get_or_create(
        term=term, course=course, code='A', defaults={'capacity': 40})

    return {
        'accounts': Account.objects.count(),
        'units': OrganizationUnit.objects.count(),
        'records': StudentRecord.objects.count(),
        'sections': TeachingSection.objects.count(),
        'department': department.code,
    }


def verify():
    from django.contrib.auth.models import Group
    from django.db import connection

    from r21_account.models import Account, StudentProfile, TeacherProfile
    from smass_organization.models import StudentRecord

    checks = []

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE()')
        current = cursor.fetchone()[0]
        check('连接目标是验证库', current == DB_NAME, current)
        cursor.execute(
            'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s',
            (DB_NAME,))
        tables = cursor.fetchone()[0]
        check('表数量与模型一致（>=120）', tables >= 120, tables)
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema=%s AND index_name='PRIMARY'", (DB_NAME,))
        primary = cursor.fetchone()[0]
        check('每个表都有主键', primary >= tables, primary)
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.referential_constraints "
            "WHERE constraint_schema=%s", (DB_NAME,))
        fks = cursor.fetchone()[0]
        check('外键存在', fks > 0, fks)
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema=%s AND constraint_type='UNIQUE'", (DB_NAME,))
        uniques = cursor.fetchone()[0]
        check('唯一约束存在', uniques > 0, uniques)

    check('无未应用迁移', not _has_unapplied())
    check('角色组已初始化', Group.objects.count() >= 4, Group.objects.count())
    check('账号唯一', Account.objects.values('login_name').distinct().count()
          == Account.objects.count(), Account.objects.count())
    check('学号唯一', StudentRecord.objects.values('student_no').distinct().count()
          == StudentRecord.objects.count(), StudentRecord.objects.count())
    check('学生档案 1:1', StudentProfile.objects.count()
          <= Account.objects.count())
    check('教师档案 1:1', TeacherProfile.objects.count()
          <= Account.objects.count())

    failures = [item for item in checks if not item['ok']]
    return {'database': DB_NAME, 'tables': tables, 'foreign_keys': fks,
            'unique_constraints': uniques, 'checks': checks,
            'failures': failures, 'ok': not failures}


def _has_unapplied():
    from django.db.migrations.executor import MigrationExecutor

    from django.db import connection

    executor = MigrationExecutor(connection)
    return bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))


def main():
    parser = argparse.ArgumentParser(description='统一数据库验证环境')
    parser.add_argument('action', choices=('init', 'migrate', 'seed', 'verify',
                                           'rollback', 'plan', 'status'))
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    guard()
    if args.action == 'rollback':
        if not database_exists(DB_NAME):
            report = {'database': DB_NAME, 'dropped': False,
                      'detail': '库不存在'}
        else:
            drop_database()
            report = {'database': DB_NAME, 'dropped': True}
    elif args.action == 'status':
        report = {'database': DB_NAME, 'exists': database_exists(DB_NAME)}
    elif args.action == 'plan':
        report = {'database': DB_NAME, 'plan': run_plan()}
    else:
        if args.action == 'init':
            create_database(recreate=True)
            migrate_output = run_migrate()
        elif args.action == 'migrate':
            create_database(recreate=False)
            migrate_output = run_migrate()
        else:
            setup()
        if args.action in ('init', 'migrate'):
            setup()
        if args.action == 'seed':
            report = {'database': DB_NAME, 'seeded': seed()}
        elif args.action == 'verify':
            report = verify()
        else:
            report = {'database': DB_NAME, 'migrated': True,
                      'output_tail': migrate_output.strip().splitlines()[-5:]}

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    ok = report.get('ok', True)
    print('RESULT: {}'.format('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
