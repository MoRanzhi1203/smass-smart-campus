#!/usr/bin/env python
"""产品端冒烟：用 Django 测试客户端验证三端页面与越权拒绝。

    python scripts/product_smoke.py --json out.json

不启动服务器、不写正式库；只访问 ``smass.settings_product`` 指向的隔离库。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STUDENT_URLS = [
    '/student/', '/student/timetable/', '/student/courses/', '/student/record/',
    '/student/attendance/', '/student/fees/', '/student/bookings/',
    '/student/activities/', '/student/volunteer/', '/student/clubs/',
    '/student/organizations/', '/student/dormitory/', '/student/notices/',
    '/notifications/', '/profile/',
]
TEACHER_URLS = [
    '/teacher/', '/teacher/courses/', '/teacher/sections/', '/teacher/timetable/',
    '/teacher/attendance/', '/teacher/students/', '/teacher/approvals/',
    '/teacher/notices/', '/notifications/', '/profile/',
]
COUNSELOR_URLS = [
    '/teacher/classes/', '/teacher/counselor/students/', '/teacher/counselor/leaves/',
]
ADMIN_URLS = [
    '/admin/', '/admin/users/', '/admin/roles/', '/admin/organizations/',
    '/admin/records/', '/admin/record-changes/', '/admin/academics/',
    '/admin/sections/', '/admin/scheduling/', '/admin/facilities/',
    '/admin/booking-approvals/', '/admin/approvals/', '/admin/workflows/',
    '/admin/activities/', '/admin/clubs/', '/admin/notices/',
    '/admin/data-exchange/', '/admin/monitoring/', '/admin/audit/',
    '/notifications/', '/profile/',
]


def setup():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_product'
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.conf import settings

    return settings


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def login(client, login_name, secret):
    response = client.post('/login/', {'login_name': login_name,
                                      'password': secret})
    return response.status_code, response.headers.get('Location', '')


def probe(client, urls, expect=200):
    result = []
    for url in urls:
        response = client.get(url, follow=False)
        result.append({'url': url, 'status': response.status_code,
                       'ok': response.status_code == expect})
    return result


def main():
    parser = argparse.ArgumentParser(description='产品端冒烟')
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    setup()
    from django.test import Client

    secret = password()
    report = {'password_source': 'env/.env', 'roles': {}}
    failures = []

    def run_role(name, login_name, urls, expect=200):
        client = Client()
        status, location = login(client, login_name, secret)
        rows = probe(client, urls, expect=expect)
        bad = [row for row in rows if not row['ok']]
        report['roles'][name] = {
            'login_status': status, 'landing': location, 'pages': rows,
            'failures': bad,
        }
        failures.extend(['{}: {} -> {}'.format(name, row['url'], row['status'])
                         for row in bad])
        return client

    run_role('student', 'dev_student', STUDENT_URLS)

    teacher = run_role('teacher', 'dev_teacher', TEACHER_URLS)
    # 教师越权：学生端与管理端必须 403
    for url in ('/student/', '/admin/'):
        response = teacher.get(url)
        ok = response.status_code == 403
        report['roles']['teacher'].setdefault('denials', []).append(
            {'url': url, 'status': response.status_code, 'ok': ok})
        if not ok:
            failures.append('teacher: {} 期望 403 实得 {}'.format(
                url, response.status_code))

    counselor = run_role('counselor', 'dev_counselor', COUNSELOR_URLS)
    response = counselor.get('/admin/')
    report['roles']['counselor']['admin_denied'] = response.status_code == 403
    if response.status_code != 403:
        failures.append('counselor: /admin/ 期望 403')

    # 动态页面：学籍详情的学号与教学班名单的主键来自真实数据
    from smass_academic.models import TeachingSection
    from smass_organization.models import StudentRecord

    student = StudentRecord.objects.filter(account__isnull=False).first()
    section = TeachingSection.objects.first()
    dynamic = []
    if student is not None:
        dynamic.append('/admin/records/{}/'.format(student.student_no))
    if section is not None:
        dynamic.append('/admin/sections/{}/roster/'.format(section.pk))

    college = run_role('college_admin', 'dev_college', ADMIN_URLS)
    response = college.get('/admin/settings/')
    report['roles']['college_admin']['settings_status'] = response.status_code
    if response.status_code != 403:
        failures.append('college_admin: /admin/settings/ 期望 403')

    run_role('super_admin', 'dev_admin', ADMIN_URLS + dynamic
             + ['/admin/settings/'])

    # 匿名访问工作台 → 302 到 /login/?next=
    anonymous = Client()
    response = anonymous.get('/student/')
    report['anonymous'] = {'status': response.status_code,
                           'location': response.headers.get('Location', '')}
    if response.status_code != 302 or '/login/' not in response.headers.get(
            'Location', ''):
        failures.append('anonymous: /student/ 未重定向到 /login/')

    report['ok'] = not failures
    report['failures'] = failures
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
