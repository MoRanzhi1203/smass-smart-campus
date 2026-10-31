#!/usr/bin/env python
"""断库运行测试：在统一验证库中临时重命名 app01 旧业务表，验证产品三端仍可运行。

    python scripts/db_unify_detached_test.py --json out.json

只操作 ``smass_unified_verify``；结束时恢复表名（finally）。
不触碰正式库与产品开发库。
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
DB_NAME = os.environ.get('UNIFIED_DB', 'smass_unified_verify')

LEGACY_TABLES = (
    'app01_student', 'app01_teacher', 'app01_admin', 'app01_classes',
    'app01_college', 'app01_major', 'app01_grade', 'app01_department',
    'app01_classcommittee', 'app01_leaguecadres', 'app01_building',
    'app01_dormitory', 'app01_dormitorynumber', 'app01_nation',
    'app01_position', 'app01_teacherposition',
)

PAGES = {
    'uni_student': ['/student/', '/student/record/', '/student/dormitory/',
                    '/student/attendance/', '/student/timetable/'],
    'uni_teacher': ['/teacher/', '/teacher/students/', '/teacher/attendance/'],
    'uni_admin': ['/admin/', '/admin/records/', '/admin/users/',
                  '/admin/organizations/', '/admin/settings/'],
}


def guard():
    if not DB_NAME.startswith('smass_unified_verify'):
        raise SystemExit('拒绝操作非验证库：{!r}'.format(DB_NAME))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()
    guard()
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    import django

    django.setup()
    from django.db import connection
    from django.test import Client

    existing = set(connection.introspection.table_names())
    to_rename = [table for table in LEGACY_TABLES if table in existing]
    renamed = []
    results = []
    try:
        with connection.cursor() as cursor:
            for table in to_rename:
                cursor.execute(
                    'RENAME TABLE `{}` TO `_retired_{}`'.format(table, table))
                renamed.append(table)
        password = os.environ.get('UNIFIED_SEED_PASSWORD') or 'Unified-Dev-2026'
        for login_name, urls in PAGES.items():
            client = Client()
            response = client.post('/login/', {
                'login_name': login_name, 'password': password})
            results.append({'role': login_name, 'url': '/login/',
                            'status': response.status_code,
                            'landing': response.headers.get('Location', '')})
            for url in urls:
                page = client.get(url)
                results.append({'role': login_name, 'url': url,
                                'status': page.status_code})
    finally:
        with connection.cursor() as cursor:
            for table in renamed:
                cursor.execute(
                    'RENAME TABLE `_retired_{}` TO `{}`'.format(table, table))

    failures = [item for item in results
                if item['status'] not in (200, 302)]
    report = {
        'database': DB_NAME,
        'renamed_tables': renamed,
        'pages_checked': len(results),
        'results': results,
        'failures': failures,
        'ok': not failures and bool(renamed),
    }
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
