#!/usr/bin/env python
"""V2.1 仿真库浏览器走查：宿舍三端 + 关键业务页（真实 Chromium）。

    python scripts/walkthrough_simulation.py --base http://127.0.0.1:8051
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.local/evidence/v21/walkthrough'

ACCOUNTS = {
    'student': 'sim_stu_S202300001',
    'teacher': 'sim_tea_T000001',
    'dorm_manager': 'sim_dorm_m01',
    'admin': 'sim_adm_01_admin',
}

PAGES = {
    'student': [
        ('/student/dormitory/', '宿舍'),
        ('/student/timetable/', '课表'),
        ('/student/activities/', '活动'),
        ('/student/attendance/', '考勤'),
    ],
    'teacher': [
        ('/teacher/sections/', '教学班'),
        ('/teacher/attendance/stats/', '考勤统计'),
        ('/teacher/timetable/', '课表'),
    ],
    'dorm_manager': [
        ('/dormitory/', '宿舍工作台'),
        ('/dormitory/rooms/', '房间'),
    ],
    'admin': [
        ('/admin/records/', '学籍'),
        ('/admin/dormitory/', '宿舍管理'),
        ('/admin/scheduling/', '排课'),
    ],
}

VIEWPORTS = [(1366, 768, 'desktop'), (390, 844, 'mobile')]


def password():
    return os.environ.get('SIMULATION_PASSWORD', 'Sim#2026demo')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8051')
    parser.add_argument('--json', dest='json_path',
                        default=str(OUT / 'walkthrough.json'))
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, pages in PAGES.items():
            for width, height, label in VIEWPORTS:
                context = browser.new_context(
                    viewport={'width': width, 'height': height})
                page = context.new_page()
                try:
                    page.goto(args.base + '/login/',
                              wait_until='domcontentloaded')
                    page.fill('input[name="login_name"]', ACCOUNTS[role])
                    page.fill('input[name="password"]', password())
                    page.click('button[type="submit"]')
                    page.wait_for_load_state('networkidle')
                    results.append({'role': role, 'viewport': label,
                                    'url': '/login/', 'status': 200,
                                    'ok': '/login/' not in page.url})
                    for url, keyword in pages:
                        response = page.goto(args.base + url,
                                             wait_until='networkidle')
                        status = response.status if response else 0
                        text = page.inner_text('body')
                        ok = (status == 200 and keyword in text
                              and 'Server Error' not in text)
                        shot = '{}-{}-{}.png'.format(
                            role, url.strip('/').replace('/', '-'), label)
                        page.screenshot(path=str(OUT / shot))
                        results.append({'role': role, 'viewport': label,
                                        'url': url, 'status': status,
                                        'keyword': keyword, 'ok': ok,
                                        'screenshot': str(OUT / shot)})
                finally:
                    context.close()
        browser.close()

    failed = [item for item in results if not item['ok']]
    report = {'checks': len(results), 'failed': failed, 'ok': not failed}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    for item in results:
        print('{:<13} {:<7} {:<28} {}'.format(
            item['role'], item['viewport'], item['url'],
            'OK' if item['ok'] else 'FAIL'))
    print('RESULT: {}'.format('PASS' if not failed else 'FAIL'))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
