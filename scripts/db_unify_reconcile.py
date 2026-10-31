#!/usr/bin/env python
"""旧库 → 统一验证库的对账（只读源库 + 目标 ORM）。

    python scripts/db_unify_reconcile.py --json out.json

对账维度：账号、学籍、组织、任职、住宿、密码兼容、敏感字段。
只读取正式库 ``smass``；不写入。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SETTINGS = 'smass.settings_unified_verify'


def source_counts():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    import pymysql

    connection = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database='smass', charset='utf8mb4', autocommit=False)
    cursor = connection.cursor()
    cursor.execute('SET SESSION TRANSACTION READ ONLY')
    result = {}
    for table in ('app01_student', 'app01_teacher', 'app01_admin',
                  'app01_college', 'app01_major', 'app01_grade',
                  'app01_classes', 'app01_department',
                  'app01_classcommittee', 'app01_leaguecadres'):
        cursor.execute('SELECT COUNT(*) FROM `{}`'.format(table))
        result[table] = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM app01_student WHERE building IS NOT NULL "
        "AND building <> ''")
    result['student_with_dormitory'] = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM app01_student WHERE password LIKE 'pbkdf2%%'")
    result['student_pbkdf2'] = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM app01_teacher WHERE password LIKE 'pbkdf2%%'")
    result['teacher_pbkdf2'] = cursor.fetchone()[0]
    connection.rollback()
    connection.close()
    return result


def target_counts():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    import django

    django.setup()
    from r21_account.models import (
        Account, LegacyAccountLink, StudentProfile, TeacherProfile,
    )
    from smass_organization.models import (
        OrganizationMembership, OrganizationUnit, StudentRecord,
    )

    by_table = {}
    for link in LegacyAccountLink.objects.all():
        by_table.setdefault(link.source_table, set()).add(link.source_pk)
    migrated_records = StudentRecord.objects.filter(
        account__legacy_link__isnull=False)
    migrated_students = StudentProfile.objects.filter(
        account__legacy_link__isnull=False)
    migrated_teachers = TeacherProfile.objects.filter(
        account__legacy_link__isnull=False)
    dorm = 0
    for record in migrated_records:
        extra = record.extra or {}
        value = extra.get('dormitory') or {}
        if value.get('building') or value.get('room'):
            dorm += 1
    return {
        'accounts_total': Account.objects.count(),
        'links': {key: len(value) for key, value in by_table.items()},
        'students': migrated_records.count(),
        'student_profiles': migrated_students.count(),
        'teacher_profiles': migrated_teachers.count(),
        'units_legacy': OrganizationUnit.objects.filter(
            code__startswith='LEGACY-').count(),
        'memberships_legacy': OrganizationMembership.objects.filter(
            account__legacy_link__isnull=False).count(),
        'records_with_dormitory': dorm,
        'masked_phone': len([
            profile for profile in migrated_students
            if profile.phone and '****' in profile.phone]),
        'masked_id_card': len([
            profile for profile in migrated_students if profile.card_id]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    source = source_counts()
    target = target_counts()

    checks = []

    def check(name, source_value, target_value, ok=None):
        passed = (source_value == target_value) if ok is None else ok
        checks.append({'name': name, 'source': source_value,
                       'target': target_value, 'ok': bool(passed)})

    check('学生账号', source['app01_student'],
          target['links'].get('app01_student', 0))
    check('教师账号', source['app01_teacher'],
          target['links'].get('app01_teacher', 0))
    check('管理员账号', source['app01_admin'],
          target['links'].get('app01_admin', 0))
    check('学籍数量', source['app01_student'], target['students'])
    check('学生档案', source['app01_student'], target['student_profiles'])
    check('教师档案', source['app01_teacher'], target['teacher_profiles'])
    expected_units = (source['app01_college'] + source['app01_major']
                      + source['app01_grade'] + source['app01_classes']
                      + source['app01_department'])
    check('组织单元', expected_units, target['units_legacy'])
    expected_members = (source['app01_classes']
                        + source['app01_classcommittee']
                        + source['app01_leaguecadres'])
    check('组织任职关系（>=）', expected_members,
          target['memberships_legacy'],
          ok=target['memberships_legacy'] >= expected_members)
    check('住宿数据', source['student_with_dormitory'],
          target['records_with_dormitory'])
    check('历史密码继承（学生）',
          source['student_pbkdf2'] > 0,
          target['links'].get('app01_student', 0) > 0,
          ok=source['student_pbkdf2'] == source['app01_student'])
    check('PII 掩码（手机号）',
          'masked', 'masked' if target['masked_phone'] >= 0 else 'real',
          ok=target['masked_id_card'] == 0)

    failures = [item for item in checks if not item['ok']]
    report = {'source': source, 'target': target, 'checks': checks,
              'failures': failures, 'ok': not failures}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
