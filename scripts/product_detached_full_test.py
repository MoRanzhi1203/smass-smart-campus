#!/usr/bin/env python
"""P3：产品库在 app01 旧业务表不可用时的全业务验证。

    python scripts/product_detached_full_test.py --json out.json

步骤：
1. 临时重命名产品库的 16 张 app01 旧业务表（保留安全状态/设备表）；
2. 五类账号登录；
3. 遍历产品三端全部页面；
4. 执行写操作：学生请假 → 教师审批 → 学生端同步；管理员公告/活动；
   场地预约 → 审批；
5. 校验数据库持久化；
6. finally 恢复表名。

只操作 ``smass_product_dev``；不触碰正式库。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SETTINGS = 'smass.settings_product'
TARGET_DB = 'smass_product_dev'

LEGACY_TABLES = (
    'app01_student', 'app01_teacher', 'app01_admin', 'app01_classes',
    'app01_college', 'app01_major', 'app01_grade', 'app01_department',
    'app01_classcommittee', 'app01_leaguecadres', 'app01_building',
    'app01_dormitory', 'app01_dormitorynumber', 'app01_nation',
    'app01_position', 'app01_teacherposition',
)

PAGES = {
    'student': [
        '/student/', '/student/timetable/', '/student/courses/',
        '/student/record/', '/student/attendance/', '/student/fees/',
        '/student/bookings/', '/student/activities/', '/student/volunteer/',
        '/student/clubs/', '/student/organizations/', '/student/dormitory/',
        '/student/notices/', '/notifications/', '/profile/',
    ],
    'teacher': [
        '/teacher/', '/teacher/courses/', '/teacher/sections/',
        '/teacher/timetable/', '/teacher/attendance/', '/teacher/students/',
        '/teacher/approvals/', '/teacher/notices/', '/notifications/', '/profile/',
    ],
    'counselor': [
        '/teacher/', '/teacher/classes/', '/teacher/counselor/students/',
        '/teacher/counselor/leaves/',
    ],
    'college_admin': ['/admin/', '/admin/records/', '/admin/users/'],
    'admin': [
        '/admin/', '/admin/users/', '/admin/roles/', '/admin/organizations/',
        '/admin/records/', '/admin/record-changes/', '/admin/academics/',
        '/admin/sections/', '/admin/scheduling/', '/admin/facilities/',
        '/admin/booking-approvals/', '/admin/approvals/', '/admin/workflows/',
        '/admin/activities/', '/admin/clubs/', '/admin/notices/',
        '/admin/data-exchange/', '/admin/monitoring/', '/admin/audit/',
        '/admin/settings/', '/notifications/', '/profile/',
    ],
}

ACCOUNTS = {
    'student': 'dev_student', 'teacher': 'dev_teacher',
    'counselor': 'dev_counselor', 'college_admin': 'dev_college',
    'admin': 'dev_admin',
}


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    import django

    django.setup()
    from django.db import connection
    from django.test import Client

    from smass_activities.models import ActivityRegistration
    from smass_attendance.models import LeaveRequest
    from smass_facilities.models import RoomBooking
    from smass_forum.models import Announcement
    from smass_organization.models import StudentRecord

    existing = set(connection.introspection.table_names())
    to_rename = [table for table in LEGACY_TABLES if table in existing]
    renamed = []
    results = []
    writes = []

    def record(role, url, status, kind='page'):
        results.append({'role': role, 'url': url, 'status': status, 'kind': kind})

    secret = password()
    try:
        with connection.cursor() as cursor:
            for table in to_rename:
                cursor.execute(
                    'RENAME TABLE `{}` TO `_retired_{}`'.format(table, table))
                renamed.append(table)

        clients = {}
        for role, login_name in ACCOUNTS.items():
            client = Client()
            response = client.post('/login/', {
                'login_name': login_name, 'password': secret})
            clients[role] = client
            record(role, '/login/', response.status_code, 'login')
            for url in PAGES[role]:
                record(role, url, client.get(url).status_code)

        # ---- 写操作 1：学生请假 → 教师审批 → 学生端同步 ----
        student_record = StudentRecord.objects.filter(
            account__login_name='dev_student').first()
        start = date.today() + timedelta(days=200)
        response = clients['student'].post('/student/attendance/leave/', {
            'leave_type': 'personal',
            'start_date': start.isoformat(),
            'end_date': (start + timedelta(days=1)).isoformat(),
            'reason': '断库验证：全业务写操作',
        })
        record('student', '/student/attendance/leave/', response.status_code, 'write')
        leave = LeaveRequest.objects.filter(
            record=student_record, reason='断库验证：全业务写操作').first()
        writes.append({'name': '请假创建', 'ok': leave is not None})

        if leave is not None:
            response = clients['teacher'].post(
                '/teacher/approvals/leave/{}/approve/'.format(leave.pk))
            leave.refresh_from_db()
            writes.append({'name': '教师审批', 'ok': leave.status == 'approved'})
            body = clients['student'].get(
                '/student/attendance/').content.decode('utf-8', 'ignore')
            writes.append({'name': '学生端同步', 'ok': '已批准' in body})

        # ---- 写操作 2：管理员公告 → 学生端可见 ----
        title = '断库验证公告-{}'.format(date.today().isoformat())
        response = clients['admin'].post('/admin/notices/create/', {
            'title': title, 'body': '断库条件下创建', 'audience': 'student',
            'publish': '1'})
        record('admin', '/admin/notices/create/', response.status_code, 'write')
        writes.append({'name': '公告创建',
                       'ok': Announcement.objects.filter(
                           title=title, status='published').exists()})
        body = clients['student'].get('/student/notices/').content.decode(
            'utf-8', 'ignore')
        writes.append({'name': '学生端看到公告', 'ok': title in body})

        # ---- 写操作 3：管理员创建活动 → 学生报名 ----
        activity_title = '断库验证活动-{}'.format(date.today().isoformat())
        response = clients['admin'].post('/admin/activities/create/', {
            'title': activity_title, 'category': 'second_class',
            'start_at': '2027-06-01T10:00', 'end_at': '2027-06-01T12:00',
            'location': '断库验证教室', 'capacity': '30',
            'credit_points': '1', 'publish': '1'})
        record('admin', '/admin/activities/create/', response.status_code, 'write')
        from smass_activities.models import Activity

        activity = Activity.objects.filter(title=activity_title).first()
        if activity is not None:
            response = clients['student'].post(
                '/student/activities/{}/register/'.format(activity.pk))
            writes.append({'name': '活动报名',
                           'ok': ActivityRegistration.objects.filter(
                               activity=activity,
                               record=student_record).exists()})

        # ---- 写操作 4：学生预约场地 → 管理员审批 ----
        from smass_facilities.models import Room

        room = Room.objects.filter(requires_approval=True).first()
        if room is not None:
            response = clients['student'].post('/student/bookings/create/', {
                'room': room.pk, 'start_at': '2027-06-02T14:00',
                'end_at': '2027-06-02T16:00', 'purpose': '断库验证预约',
                'attendees': '5'})
            record('student', '/student/bookings/create/', response.status_code,
                   'write')
            booking = RoomBooking.objects.filter(
                purpose='断库验证预约').order_by('-pk').first()
            writes.append({'name': '场地预约', 'ok': booking is not None})
            if booking is not None:
                clients['admin'].post(
                    '/admin/bookings/{}/approve/'.format(booking.pk))
                booking.refresh_from_db()
                writes.append({'name': '场地审批', 'ok': booking.status == 'approved'})
    finally:
        with connection.cursor() as cursor:
            for table in renamed:
                cursor.execute(
                    'RENAME TABLE `_retired_{}` TO `{}`'.format(table, table))

    page_failures = [item for item in results
                     if item['status'] not in (200, 302)]
    write_failures = [item for item in writes if not item['ok']]
    report = {
        'database': TARGET_DB,
        'renamed_tables': renamed,
        'pages_checked': len(results),
        'page_failures': page_failures,
        'write_checks': writes,
        'write_failures': write_failures,
        'ok': not page_failures and not write_failures and bool(renamed),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(json.dumps({key: report[key] for key in (
        'database', 'renamed_tables', 'pages_checked', 'page_failures',
        'write_checks', 'write_failures', 'ok')}, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
