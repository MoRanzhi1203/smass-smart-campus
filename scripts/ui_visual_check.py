#!/usr/bin/env python
"""V2.0 视觉检查：三端 × 四档视口截图 + 横向溢出检测。

    python scripts/ui_visual_check.py --base http://127.0.0.1:8050

输出：.local/evidence/v2/screenshots/*.png + ui_visual_check.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.local/evidence/v2'

ACCOUNTS = {
    'student': ('dev_student', '/student/'),
    'teacher': ('dev_teacher', '/teacher/'),
    'admin': ('dev_admin', '/admin/'),
}
VIEWPORTS = [(390, 844, 'mobile'), (768, 1024, 'tablet'),
             (1366, 768, 'laptop'), (1920, 1080, 'desktop')]


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8050')
    parser.add_argument('--json', dest='json_path',
                        default=str(OUT / 'ui_visual_check.json'))
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    secret = password()
    shots = OUT / 'screenshots'
    shots.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, (login_name, path) in ACCOUNTS.items():
            for width, height, label in VIEWPORTS:
                context = browser.new_context(
                    viewport={'width': width, 'height': height},
                    device_scale_factor=1)
                page = context.new_page()
                try:
                    page.goto(args.base + '/login/', wait_until='domcontentloaded')
                    page.fill('input[name="login_name"]', login_name)
                    page.fill('input[name="password"]', secret)
                    page.click('button[type="submit"]')
                    page.wait_for_load_state('networkidle')
                    page.goto(args.base + path + '?v=2', wait_until='networkidle')
                    metrics = page.evaluate(
                        """() => ({
                            scrollWidth: document.documentElement.scrollWidth,
                            clientWidth: document.documentElement.clientWidth,
                            scrollHeight: document.documentElement.scrollHeight,
                            bodyOverflowX: getComputedStyle(document.body).overflowX,
                            accent: getComputedStyle(document.body)
                                .getPropertyValue('--ws-accent').trim(),
                            cards: document.querySelectorAll('.ws-card').length,
                            tables: document.querySelectorAll('table').length,
                            buttons: document.querySelectorAll('.ws-btn').length,
                        })""")
                    overflow = metrics['scrollWidth'] > metrics['clientWidth'] + 2
                    name = '{}-{}-{}.png'.format(role, label, width)
                    page.screenshot(path=str(shots / name), full_page=False)
                    results.append({
                        'role': role, 'viewport': '{}x{}'.format(width, height),
                        'label': label, 'overflow_x': overflow,
                        'scroll_width': metrics['scrollWidth'],
                        'client_width': metrics['clientWidth'],
                        'accent': metrics['accent'],
                        'cards': metrics['cards'], 'tables': metrics['tables'],
                        'buttons': metrics['buttons'],
                        'screenshot': str(shots / name),
                    })
                finally:
                    context.close()
        browser.close()

    failures = [item for item in results if item['overflow_x']]
    report = {'base': args.base, 'checks': results,
              'overflow_failures': failures, 'ok': not failures}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps({'checks': len(results),
                      'overflow_failures': len(failures),
                      'ok': report['ok']}, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
