#!/usr/bin/env python
"""P8 仿真库页面性能采样：查询数、耗时、状态码。

    python scripts/perf_simulation.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_simulation')

PAGES = [
    ('admin', 'sim_adm_01_admin', '/admin/records/', '学籍列表'),
    ('admin', 'sim_adm_01_admin', '/admin/users/', '账号列表'),
    ('admin', 'sim_adm_01_admin', '/admin/dormitory/', '宿舍管理'),
    ('admin', 'sim_adm_01_admin', '/admin/scheduling/', '排课管理'),
    ('teacher', 'sim_tea_T000001', '/teacher/sections/', '教学班名单'),
    ('teacher', 'sim_tea_T000001', '/teacher/attendance/stats/', '班级考勤统计'),
    ('teacher', 'sim_tea_T000001', '/teacher/timetable/', '教师课表'),
    ('student', 'sim_stu_S202300001', '/student/timetable/', '学生课表'),
    ('student', 'sim_stu_S202300001', '/student/dormitory/', '学生住宿'),
    ('student', 'sim_stu_S202300001', '/student/activities/', '活动列表'),
    ('dorm', 'sim_dorm_m01', '/dormitory/', '宿管工作台'),
    ('dorm', 'sim_dorm_m01', '/dormitory/rooms/', '房间浏览'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path',
                        default=str(ROOT / '.local/evidence/v21/perf_sim.json'))
    args = parser.parse_args()

    import django

    django.setup()
    from django.db import connection
    from django.test import Client
    from django.test.utils import CaptureQueriesContext

    from smass_simulation.generator.people import password

    secret = os.environ.get('SIMULATION_PASSWORD', password())
    results = []
    for role, login, url, label in PAGES:
        client = Client()
        login_response = client.post('/login/', {
            'login_name': login, 'password': secret}, follow=False)
        if login_response.status_code not in (302, 200):
            results.append({'role': role, 'label': label, 'url': url,
                            'status': 0, 'queries': 0, 'ms': 0,
                            'error': 'login failed {}'.format(
                                login_response.status_code)})
            continue
        with CaptureQueriesContext(connection) as captured:
            started = time.perf_counter()
            response = client.get(url)
            elapsed = (time.perf_counter() - started) * 1000
        results.append({
            'role': role, 'label': label, 'url': url,
            'status': response.status_code,
            'queries': len(captured.captured_queries),
            'ms': round(elapsed, 1),
            'bytes': len(response.content),
        })
    report = {'pages': results,
              'ok': all(item.get('status') == 200 for item in results)}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    for item in results:
        print('{:<26} {:<8} status={:<4} queries={:<4} {} ms'.format(
            item['label'], item['role'], item.get('status'),
            item.get('queries'), item.get('ms')))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
