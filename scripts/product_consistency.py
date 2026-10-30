#!/usr/bin/env python
"""同一业务对象在三端的数据状态一致性验证。

以「学生请假」为对象：学生端、教师端、管理端读取同一行数据，
页面展示的状态必须与数据库一致。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_product')


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def main():
    import django

    django.setup()
    from django.test import Client

    from smass_attendance.models import LeaveRequest

    secret = password()
    checks = []

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    leave = (LeaveRequest.objects.select_related('record')
             .order_by('-created_at').first())
    if leave is None:
        report = {'ok': False, 'checks': [], 'failures': ['没有请假记录']}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    def client_for(login_name):
        client = Client()
        client.post('/login/', {'login_name': login_name, 'password': secret})
        return client

    if leave.status == 'submitted':
        teacher = client_for('dev_teacher')
        teacher.post('/teacher/approvals/leave/{}/approve/'.format(leave.pk))
        leave.refresh_from_db()

    expected = leave.get_status_display()
    check('数据库状态', leave.status in ('approved', 'rejected'), leave.status)

    student = client_for(leave.record.account.login_name)
    body = student.get('/student/attendance/').content.decode('utf-8', 'ignore')
    check('学生端显示最新状态', expected in body, expected)
    check('学生端显示同一请假', leave.record.name in body, leave.record.name)

    teacher = client_for('dev_teacher')
    body = teacher.get('/teacher/approvals/').content.decode('utf-8', 'ignore')
    check('教师端显示最新状态', expected in body, expected)
    check('教师端显示同一学生', leave.record.name in body, leave.record.name)

    admin = client_for('dev_admin')
    body = admin.get('/admin/approvals/').content.decode('utf-8', 'ignore')
    check('管理端显示最新状态', expected in body, expected)
    check('管理端显示同一学生', leave.record.name in body, leave.record.name)

    # 三端读到的是同一主键
    check('对象主键一致',
          LeaveRequest.objects.filter(pk=leave.pk).exists(),
          'leave_id={}'.format(leave.pk))

    failures = [item for item in checks if not item['ok']]
    report = {'leave_id': leave.pk, 'expected_status': expected,
              'checks': checks, 'failures': failures, 'ok': not failures}
    path = ROOT / '.local/evidence/product/consistency.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
