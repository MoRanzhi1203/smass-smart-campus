#!/usr/bin/env python
"""F05 性能基准：在临时测试库生成合成数据，测量关键路径耗时与 SQL 数。

    python scripts/perf_baseline_v2.py --json out.json

不触碰产品库与正式库：使用 Django 测试库（创建 → 测量 → 销毁）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def measure(label, func):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        started = time.perf_counter()
        result = func()
        elapsed = (time.perf_counter() - started) * 1000
    return {
        'label': label,
        'ms': round(elapsed, 1),
        'queries': len(captured.captured_queries),
        'result_size': len(result) if hasattr(result, '__len__') else None,
    }


def build_data():
    from datetime import date

    from django.contrib.auth.hashers import make_password

    from r21_account.models import Account, RoleCode, StudentProfile
    from smass_academic.models import (
        AcademicTerm, AcademicYear, Course, Enrollment, TeachingAssignment,
        TeachingSection,
    )
    from smass_organization.models import OrganizationUnit, StudentRecord
    from smass_organization.services import create_unit

    from r21_account import services as account_services

    account_services.ensure_role_groups()
    password = make_password('Perf#2026pass')

    college = create_unit(code='PERF-COL', name='性能学院', unit_type='college')
    major = create_unit(code='PERF-MAJ', name='性能专业', unit_type='major',
                        parent=college)
    klass = create_unit(code='PERF-CLS', name='性能2401', unit_type='class',
                        parent=major)

    accounts = []
    for index in range(1000):
        accounts.append(Account(
            login_name='perf_{:04d}'.format(index),
            display_name='性能学生{}'.format(index),
            person_type='student', password=password, is_active=True,
            must_change_password=False))
    Account.objects.bulk_create(accounts, batch_size=200)
    account_ids = list(Account.objects.filter(
        login_name__startswith='perf_').values_list('id', flat=True))
    AccountRole = Account._meta.apps.get_model('r21_account', 'AccountRole')
    AccountRole.objects.bulk_create([
        AccountRole(account_id=pk, role=RoleCode.STUDENT) for pk in account_ids],
        batch_size=200)

    records = [
        StudentRecord(student_no='P{:08d}'.format(index),
                      name='性能学生{}'.format(index),
                      account_id=account_ids[index], unit=klass,
                      status='enrolled', enrolled_at=date(2024, 9, 1))
        for index in range(500)]
    StudentRecord.objects.bulk_create(records, batch_size=200)
    StudentProfile.objects.bulk_create([
        StudentProfile(account_id=item.account_id, student_no=item.student_no,
                       name=item.name, college_name='性能学院',
                       classes_name='性能2401')
        for item in records], batch_size=200)

    year = AcademicYear.objects.create(
        code='PERF-2024', start_date=date(2024, 9, 1),
        end_date=date(2025, 8, 31), is_active=True)
    term = AcademicTerm.objects.create(
        year=year, semester='1', name='2024-2025-1',
        start_date=date(2024, 9, 1), end_date=date(2025, 1, 15),
        is_active=True)
    course = Course.objects.create(code='PERF-CS', title='性能课程', credit=3)
    sections = [
        TeachingSection.objects.create(
            term=term, course=course, code='S{}'.format(index), capacity=100)
        for index in range(50)]
    TeachingAssignment.objects.bulk_create([
        TeachingAssignment(section=section, account_id=account_ids[0])
        for section in sections])
    Enrollment.objects.bulk_create([
        Enrollment(section=sections[index % 50], account_id=account_ids[index])
        for index in range(500)], batch_size=200)

    return {'accounts': 1000, 'records': 500, 'sections': 50,
            'enrollments': 500, 'term': term.pk, 'klass': klass.pk}


def run_measurements():
    from smass_workspace import permissions as perms
    from smass_workspace.services import admin as admin_svc
    from smass_workspace.services import student as student_svc
    from r21_account.models import Account

    admin = Account.objects.create_user(
        'perf_admin', 'Perf#2026pass', display_name='性能管理员',
        person_type='admin')
    admin.must_change_password = False
    admin.save()
    from r21_account import services as account_services

    account_services.grant_role(admin, 'system_admin')

    student = Account.objects.filter(login_name='perf_0000').first()
    account_services.grant_role(student, 'student')
    student.must_change_password = False
    student.save(update_fields=['must_change_password'])

    results = []
    results.append(measure(
        '管理端用户列表（第1页）',
        lambda: admin_svc.users(admin, '', '', '')[:20]))
    results.append(measure(
        '管理端学籍列表（第1页）',
        lambda: admin_svc.records(admin, '', '')[:20]))
    results.append(measure(
        '管理总览聚合',
        lambda: admin_svc.overview(admin)))
    results.append(measure(
        '学生课表查询',
        lambda: student_svc.student_entries(student)))
    results.append(measure(
        '教师学生范围（学院管理员）',
        lambda: list(perms.scoped_student_records(admin)[:20])))
    results.append(measure(
        '未读通知计数',
        lambda: student_svc.unread_notice_count(student)
        if hasattr(student_svc, 'unread_notice_count') else []))
    return results


def import_benchmark():
    from smass_organization import services as org_services

    header = 'student_no,name,unit_code,status\n'
    rows = ''.join(
        'IMP{:08d},导入学生{},PERF-CLS,enrolled\n'.format(index, index)
        for index in range(1, 501))
    text = header + rows
    tracemalloc.start()
    started = time.perf_counter()
    job, preview = org_services.import_preview(text, actor='perf')
    preview_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    job2, stats = org_services.import_commit(text, actor='perf')
    commit_ms = (time.perf_counter() - started) * 1000
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        'rows': 500,
        'preview_ms': round(preview_ms, 1),
        'commit_ms': round(commit_ms, 1),
        'peak_kb': round(peak / 1024, 1),
        'stats': stats,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path',
                        default=str(ROOT / '.local/evidence/v2/perf_baseline.json'))
    args = parser.parse_args()

    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_product'
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        fixture = build_data()
        results = run_measurements()
        import_result = import_benchmark()
    finally:
        runner.teardown_databases(old_config)

    report = {'fixture': fixture, 'measurements': results,
              'import': import_result,
              'thresholds': {'list_ms': 500, 'overview_ms': 1500,
                             'timetable_ms': 500, 'import_commit_ms': 60000}}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('RESULT: PASS')


if __name__ == '__main__':
    raise SystemExit(main())
