"""为运行中的演示服务截图（Playwright，真实浏览器）。

用法：
    conda run -n smass python scripts/r10_screenshot.py
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'docs' / 'screenshots'
BASE_URL = 'http://127.0.0.1:8000'
PASSWORD = os.environ.get('SMASS_DEMO_PASSWORD', 'Demo#2024')


def main():
    sys.path.insert(0, str(BASE))

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)

    shots = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(15000)

        # 1) 统一导航（未登录）
        page.goto(BASE_URL + '/r10/')
        page.wait_for_load_state('load')
        path = OUT / '01_r10_nav.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('统一导航（未登录）', path))

        # 2) 执行登录（真实表单）
        page.goto(BASE_URL + '/r5/login/')
        page.fill('#id_login_name', 'admin')
        page.fill('#id_password', PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')

        # 登录后会被重定向到 /r10/
        page.goto(BASE_URL + '/r10/')
        page.wait_for_load_state('load')
        path = OUT / '02_r10_nav_logged_in.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('登录后导航', path))

        # 3) R4 组织单元
        page.goto(BASE_URL + '/r4/units/')
        page.wait_for_load_state('load')
        path = OUT / '03_r4_units.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('R4 组织单元', path))

        # 4) R4 学生档案
        page.goto(BASE_URL + '/r4/students/')
        page.wait_for_load_state('load')
        path = OUT / '04_r4_students.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('R4 学生档案', path))

        # 5) R5 教学班
        page.goto(BASE_URL + '/r5/sections/')
        page.wait_for_load_state('load')
        path = OUT / '05_r5_sections.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('R5 教学班', path))

        # 6) R7 看板
        page.goto(BASE_URL + '/r7/dashboard/')
        page.wait_for_load_state('load')
        path = OUT / '06_r7_dashboard.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('R7 指标看板', path))

        # 7) R6 流程实例
        page.goto(BASE_URL + '/r6/instances/')
        page.wait_for_load_state('load')
        path = OUT / '07_r6_instances.png'
        page.screenshot(path=str(path), full_page=True)
        shots.append(('R6 流程实例', path))

        browser.close()

    for label, path in shots:
        print('{:<20} {} ({} bytes)'.format(label, path.name, path.stat().st_size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
