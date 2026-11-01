#!/usr/bin/env python
"""三端主链路浏览器走查（对应交付建议第 1 项）。

登录 → 关键页面 → 关键元素/导出链接 → 截图。
不修改业务数据；只读页面与导出（导出不落库）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.local/evidence/v2/walkthrough'

ACCOUNTS = {'student': 'dev_student', 'teacher': 'dev_teacher',
            'admin': 'dev_admin'}

FLOWS = {
    'student': [
        ('/student/', '学习工作台', '我的课表'),
        ('/student/courses/', '我的课程', '选课'),
        ('/student/attendance/', '考勤与请假', '签到'),
        ('/student/timetable/', '我的课表', '教学周'),
        ('/student/fees/', '费用与账单', '账单'),
    ],
    'teacher': [
        ('/teacher/', '教学工作台', '今日'),
        ('/teacher/sections/', '教学班', '导出名单'),
        ('/teacher/attendance/stats/', '班级考勤统计', '出勤率'),
        ('/teacher/attendance/', '考勤管理', '考勤'),
        ('/teacher/approvals/', '审批', '请假'),
    ],
    'admin': [
        ('/admin/', '控制台', '总览'),
        ('/admin/organizations/', '组织', '组织'),
        ('/admin/finance/', '财务与账单', '收费项'),
        ('/admin/data-exchange/', '数据导入导出', '受控导出'),
        ('/admin/data-quality/', '数据质量', '问题'),
    ],
}

EXPORTS = [
    ('/admin/data-exchange/export/records/', 'admin', 'students-records'),
    ('/teacher/sections/export/', 'teacher', 'section-students'),
]


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD') or 'Smass#2026')


def main():
    from playwright.sync_api import sync_playwright

    secret = password()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        contexts = {}
        for role, pages in FLOWS.items():
            context = browser.new_context(viewport={'width': 1366, 'height': 768})
            page = context.new_page()
            page.goto('http://127.0.0.1:8050/login/', wait_until='domcontentloaded')
            page.fill('input[name="login_name"]', ACCOUNTS[role])
            page.fill('input[name="password"]', secret)
            page.click('button[type="submit"]')
            page.wait_for_load_state('networkidle')
            results.append({'step': 'login', 'role': role,
                            'url': page.url,
                            'ok': '/login/' not in page.url})
            for url, title, keyword in pages:
                response = page.goto('http://127.0.0.1:8050' + url,
                                     wait_until='networkidle')
                status = response.status if response else 0
                text = page.inner_text('body')
                ok = (status == 200 and keyword in text
                      and 'Server Error' not in text)
                shot = '{}-{}.png'.format(role, url.strip('/').replace('/', '-') or 'home')
                page.screenshot(path=str(OUT / shot))
                results.append({'step': 'page', 'role': role, 'url': url,
                                'status': status, 'keyword': keyword,
                                'ok': ok, 'screenshot': str(OUT / shot)})
            contexts[role] = (context, page)

        for url, role, prefix in EXPORTS:
            context, _ = contexts[role]
            response = context.request.get('http://127.0.0.1:8050' + url)
            content_type = response.headers.get('content-type', '')
            disposition = response.headers.get('content-disposition', '')
            payload = response.body()
            ok = (response.status == 200 and 'text/csv' in content_type
                  and prefix in disposition and len(payload) > 20)
            results.append({'step': 'export', 'role': role, 'url': url,
                            'status': response.status,
                            'content_type': content_type,
                            'bytes': len(payload), 'ok': ok})

        for context, _ in contexts.values():
            context.close()
        browser.close()

    failed = [item for item in results if not item['ok']]
    report = {'checks': len(results), 'failed': failed, 'ok': not failed}
    (OUT / 'walkthrough.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for item in results:
        print('{:<6} {:<8} {:<40} {}'.format(
            item['step'], item.get('role', ''), item.get('url', ''),
            'OK' if item['ok'] else 'FAIL'))
    print('RESULT: {}'.format('PASS' if not failed else 'FAIL'))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
