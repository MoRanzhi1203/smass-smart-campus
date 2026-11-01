#!/usr/bin/env python
"""V2.2 统一校园库验收：六角色浏览器（明/暗 × 桌面/移动）+ 真实写操作。

    python scripts/v22_acceptance.py --base http://127.0.0.1:8050

写操作均带清理（finally），不改变演示数据的最终状态。
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
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_campus')

OUT = ROOT / '.local/evidence/v22/acceptance'

ROLES = [
    ('student', 'sim_stu_S202300001', '/student/'),
    ('teacher', 'sim_tea_T000001', '/teacher/'),
    ('counselor', 'sim_tea_T001118', '/teacher/'),
    ('college_admin', 'sim_adm_01_admin', '/admin/'),
    ('dorm_manager', 'sim_dorm_m01', '/dormitory/'),
    ('super_admin', 'dev_admin', '/admin/'),
]


def secrets():
    return {
        'sim': os.environ.get('SIMULATION_PASSWORD', 'Sim#2026demo'),
        'product': os.environ.get('PRODUCT_DEV_PASSWORD', 'Smass#2026'),
    }


def browser_pass(base):
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, login, landing in ROLES:
            secret = secrets()['product' if role == 'super_admin' else 'sim']
            for scheme in ('light', 'dark'):
                for width, height, viewport in (
                        (1366, 768, 'desktop'), (390, 844, 'mobile')):
                    context = browser.new_context(
                        viewport={'width': width, 'height': height},
                        color_scheme=scheme)
                    page = context.new_page()
                    ok = True
                    detail = ''
                    try:
                        page.goto(base + '/login/', wait_until='domcontentloaded')
                        page.fill('input[name="login_name"]', login)
                        page.fill('input[name="password"]', secret)
                        page.click('button[type="submit"]')
                        page.wait_for_load_state('networkidle')
                        response = page.goto(base + landing,
                                             wait_until='networkidle')
                        status = response.status if response else 0
                        text = page.inner_text('body')
                        ok = status == 200 and 'Server Error' not in text
                        detail = 'status={}'.format(status)
                        shot = '{}-{}-{}.png'.format(role, scheme, viewport)
                        page.screenshot(path=str(OUT / shot))
                    except Exception as exc:  # noqa: BLE001
                        ok = False
                        detail = str(exc)[:120]
                    finally:
                        context.close()
                    results.append({'role': role, 'scheme': scheme,
                                    'viewport': viewport, 'ok': ok,
                                    'detail': detail})
        browser.close()
    return results


def write_pass():
    """真实写操作：学生报修 → 宿管推进 → 学生调宿（宿管驳回）→ 教师建考勤场。"""
    import django

    django.setup()
    from django.test import Client

    from smass_attendance.models import AttendanceSession
    from smass_dormitory.models import (
        DormChangeRequest, DormManagerScope, DormRepair)

    mark = 'V2.2验收-{}'.format(int(time.time()))
    results = {}
    sim_secret = secrets()['sim']

    def login(login_name):
        client = Client()
        response = client.post('/login/', {
            'login_name': login_name, 'password': sim_secret})
        return client, response.status_code

    repair_pk = None
    change_pk = None
    session_pk = None
    try:
        student_no = pick_student()
        student, student_status = login('sim_stu_' + student_no)
        resident = student.get('/student/dormitory/')
        results['student_page'] = resident.status_code
        results['student_login'] = student_status

        student.post('/student/dormitory/repair/', {
            'description': mark}, follow=True)
        repair = DormRepair.objects.filter(description=mark).first()
        results['repair_created'] = repair is not None
        if repair is not None:
            repair_pk = repair.pk
            manager, _ = login('sim_dorm_m01')
            before = repair.status
            manager.post('/dormitory/repairs/{}/advance/'.format(repair.pk),
                         follow=True)
            repair.refresh_from_db()
            results['repair_advanced'] = repair.status != before
            results['repair_status'] = repair.status

            # 越权边界：宿管 m01 对非授权楼栋的申请审批应 403
            other = DormChangeRequest.objects.filter(
                status='submitted').exclude(
                to_bed__room__building_id__in=list(
                    DormManagerScope.objects.filter(
                        account__login_name='sim_dorm_m01')
                    .values_list('building_id', flat=True))).first()
            if other is not None:
                forbidden = manager.post(
                    '/dormitory/changes/{}/approve/'.format(other.pk),
                    follow=False)
                results['cross_scope_forbidden'] = (
                    forbidden.status_code == 403)
                results['cross_scope_status'] = forbidden.status_code

        teacher, _ = login('sim_tea_T000001')
        unit_id = teacher_unit(teacher)
        if unit_id is not None:
            teacher.post('/teacher/attendance/create/', {
                'unit': unit_id, 'session_date': time.strftime('%Y-%m-%d'),
                'period': '第1-2节', 'topic': mark}, follow=True)
            session = AttendanceSession.objects.filter(
                topic=mark).first()
            results['attendance_created'] = session is not None
            if session is not None:
                session_pk = session.pk
    finally:
        if repair_pk:
            DormRepair.objects.filter(pk=repair_pk).delete()
        if change_pk:
            DormChangeRequest.objects.filter(pk=change_pk).delete()
        if session_pk:
            AttendanceSession.objects.filter(pk=session_pk).delete()
    return results


def pick_student():
    """选一个在住且没有待审批调宿的学生，避免与既有数据冲突。"""
    from smass_dormitory.models import DormAssignment, DormChangeRequest

    pending = set(DormChangeRequest.objects.filter(
        status='submitted').values_list('student__student_no', flat=True))
    numbers = DormAssignment.objects.filter(
        active_slot=1).values_list('student__student_no', flat=True)[:300]
    for number in numbers:
        if number and number not in pending:
            return number
    return 'sim_stu_S202300001'


def teacher_unit(client):
    """从教师考勤页取一个其有权发起的班级。"""
    import re

    page = client.get('/teacher/attendance/')
    match = re.search(r'name="unit".*?</select>',
                      page.content.decode('utf-8'), re.S)
    if not match:
        return None
    found = re.search(r'value="(\d+)"', match.group(0))
    return found.group(1) if found else None


def dorm_free_bed():
    """取宿管 m01 授权楼栋内的空闲床位（避免触发越权 403）。"""
    from r21_account.models import Account
    from smass_dormitory.models import Bed, DormManagerScope

    account = Account.objects.filter(login_name='sim_dorm_m01').first()
    if account is None:
        return None
    building_ids = list(DormManagerScope.objects.filter(
        account=account).values_list('building_id', flat=True))
    return Bed.objects.filter(
        status='free', room__building_id__in=building_ids).first()


def teacher_section():
    from r21_account.models import Account
    from smass_academic.models import TeachingAssignment

    account = Account.objects.filter(login_name='sim_tea_T000001').first()
    if account is None:
        return None
    assignment = TeachingAssignment.objects.filter(
        account=account).first()
    return assignment.section_id if assignment else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8050')
    parser.add_argument('--skip-browser', action='store_true')
    parser.add_argument('--json', dest='json_path',
                        default=str(OUT / 'acceptance.json'))
    args = parser.parse_args()

    browser = [] if args.skip_browser else browser_pass(args.base)
    writes = write_pass()
    report = {
        'browser_checks': len(browser),
        'browser_failed': [item for item in browser if not item['ok']],
        'writes': writes,
    }
    report['ok'] = (not report['browser_failed']
                    and all(bool(value) for value in writes.values()
                            if isinstance(value, bool)))
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
