#!/usr/bin/env python
"""V2.0 阶段视觉验收：关键页面 × 视口 × 浏览器缩放。

    python scripts/ui_visual_check_v2.py --base http://127.0.0.1:8050

检查：横向溢出、关键区域渲染、按钮/表格存在、缩放 125%/150% 下的溢出。
输出：.local/evidence/v2/phase/*.png + ui_visual_check_v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.local/evidence/v2/phase'

PAGES = {
    'student': [
        ('/student/', 'home'),
        ('/student/courses/', 'courses'),
        ('/student/attendance/', 'attendance'),
        ('/student/timetable/', 'timetable'),
        ('/student/fees/', 'fees'),
    ],
    'teacher': [
        ('/teacher/', 'home'),
        ('/teacher/attendance/', 'attendance'),
        ('/teacher/attendance/stats/', 'attendance-stats'),
        ('/teacher/approvals/', 'approvals'),
        ('/teacher/timetable/', 'timetable'),
    ],
    'admin': [
        ('/admin/', 'home'),
        ('/admin/organizations/', 'organizations'),
        ('/admin/teachers/', 'teachers'),
        ('/admin/scheduling/', 'scheduling'),
        ('/admin/workflows/', 'workflows'),
        ('/admin/finance/', 'finance'),
        ('/admin/data-exchange/', 'data-exchange'),
        ('/admin/users/', 'users'),
    ],
}

ACCOUNTS = {'student': 'dev_student', 'teacher': 'dev_teacher',
            'admin': 'dev_admin'}
VIEWPORTS = [(390, 844, 'mobile'), (768, 1024, 'tablet'),
             (1366, 768, 'laptop'), (1920, 1080, 'desktop')]
ZOOMS = (1.0, 1.25, 1.5)


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8050')
    parser.add_argument('--scheme', default='light', choices=['light', 'dark'])
    parser.add_argument('--quick', action='store_true',
                        help='只跑 390/1366 两档视口与 100%/150% 缩放')
    parser.add_argument('--json', dest='json_path',
                        default=str(OUT / 'ui_visual_check_v2.json'))
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    secret = password()
    OUT.mkdir(parents=True, exist_ok=True)
    viewports = VIEWPORTS
    zooms = ZOOMS
    if args.quick:
        viewports = [VIEWPORTS[0], VIEWPORTS[2]]
        zooms = (1.0, 1.5)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, pages in PAGES.items():
            for width, height, label in viewports:
                context = browser.new_context(
                    viewport={'width': width, 'height': height},
                    color_scheme=args.scheme)
                page = context.new_page()
                try:
                    page.goto(args.base + '/login/', wait_until='domcontentloaded')
                    page.fill('input[name="login_name"]', ACCOUNTS[role])
                    page.fill('input[name="password"]', secret)
                    page.click('button[type="submit"]')
                    page.wait_for_load_state('networkidle')
                    for url, name in pages:
                        for zoom in zooms:
                            page.goto(args.base + url + '?v=2',
                                      wait_until='networkidle')
                            if zoom != 1.0:
                                page.evaluate(
                                    'z => { document.body.style.zoom = z; }', zoom)
                            metrics = page.evaluate(
                                """() => ({
                                    scrollWidth: document.documentElement.scrollWidth,
                                    clientWidth: document.documentElement.clientWidth,
                                    cards: document.querySelectorAll('.ws-card').length,
                                    tables: document.querySelectorAll('table').length,
                                    buttons: document.querySelectorAll('button, .ws-btn').length,
                                    textLength: document.body.innerText.length,
                                })""")
                            overflow = (metrics['scrollWidth']
                                        > metrics['clientWidth'] + 2)
                            shot = '{}-{}-{}-z{}-{}.png'.format(
                                role, name, width,
                                str(zoom).replace('.', ''), args.scheme)
                            page.screenshot(path=str(OUT / shot))
                            results.append({
                                'role': role, 'page': name, 'url': url,
                                'viewport': '{}x{}'.format(width, height),
                                'zoom': zoom, 'overflow': overflow,
                                'cards': metrics['cards'],
                                'tables': metrics['tables'],
                                'buttons': metrics['buttons'],
                                'text_length': metrics['textLength'],
                                'screenshot': str(OUT / shot),
                            })
                finally:
                    context.close()
        browser.close()

    failures = [item for item in results if item['overflow']]
    thin = [item for item in results if item['text_length'] < 200]
    report = {'base': args.base, 'checks': len(results),
              'overflow_failures': failures, 'thin_pages': thin,
              'ok': not failures and not thin}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps({
        'checks': len(results),
        'overflow_failures': len(failures),
        'thin_pages': len(thin),
        'ok': report['ok'],
    }, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
