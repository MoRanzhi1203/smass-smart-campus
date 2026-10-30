#!/usr/bin/env python
"""产品三端真实浏览器验收（Playwright + Chromium）。

    python scripts/product_e2e.py --base http://127.0.0.1:8050

覆盖：同一登录入口、按角色落地、三端独立导航、审批跨端同步、
管理员配置后学生端可见、越权后端 403、截图证据。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def main():
    parser = argparse.ArgumentParser(description='产品三端浏览器验收')
    parser.add_argument('--base', default='http://127.0.0.1:8050')
    parser.add_argument('--shots', default=str(ROOT / '.local/evidence/product/screenshots'))
    parser.add_argument('--json', dest='json_path',
                        default=str(ROOT / '.local/evidence/product/e2e.json'))
    args = parser.parse_args()

    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    secret = password()
    base = args.base.rstrip('/')
    checks = []
    console_errors = []

    # 计算一个不与历史请假重叠的未来日期，保证脚本可重复执行
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_product')
    import django

    django.setup()
    from smass_attendance.models import LeaveRequest

    from datetime import date as _date
    from datetime import timedelta as _timedelta

    future = _date.today() + _timedelta(days=60 + LeaveRequest.objects.count())

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 960},
                                     locale='zh-CN')
        page = context.new_page()

        def shot(name):
            page.screenshot(path=str(shots / name), full_page=True)

        def login(login_name):
            page.goto(base + '/login/', wait_until='domcontentloaded')
            page.fill('#id_login_name', login_name)
            page.fill('#id_password', secret)
            page.click('#btnLogin')
            page.wait_for_load_state('domcontentloaded')

        page.on('console', lambda msg: console_errors.append(msg.text)
                if msg.type == 'error' else None)

        # 1. 未登录 → 统一登录入口
        response = page.goto(base + '/student/', wait_until='domcontentloaded')
        check('匿名访问学生端跳转登录',
              '/login/' in page.url and 'next=/student/' in page.url, page.url)
        check('登录页渲染', '统一登录入口' in page.content())
        shot('00_login.png')

        # 2. 学生端
        login('dev_student')
        check('学生登录后落在学生工作台', page.url.endswith('/student/'), page.url)
        check('学生工作台显示欢迎语', '欢迎回来' in page.content())
        shot('01_student_home.png')

        page.goto(base + '/student/timetable/', wait_until='domcontentloaded')
        body = page.content()
        check('学生课表显示课程', '程序设计基础' in body, page.url)
        shot('02_student_timetable.png')

        page.goto(base + '/student/attendance/', wait_until='domcontentloaded')
        check('学生考勤页可提交请假', '提交请假申请' in page.content())
        shot('03_student_attendance.png')

        # 提交一条未来日期的请假，保证教师端一定有待批事项（可重复执行）
        page.select_option('#leave_type', 'personal')
        page.fill('#start_date', future.isoformat())
        page.fill('#end_date', (future + _timedelta(days=1)).isoformat())
        page.fill('#reason', '验收脚本：跨端审批同步验证。')
        page.click("button:has-text('提交申请')")
        page.wait_for_load_state('domcontentloaded')
        check('学生提交请假成功', '请假申请已提交' in page.content(), page.url)

        # 3. 学生越权：管理端必须 403
        response = page.goto(base + '/admin/', wait_until='domcontentloaded')
        check('学生访问管理端返回 403',
              response is not None and response.status == 403,
              response.status if response else 'no-response')
        check('403 页面有权限说明', '没有访问该页面的权限' in page.content())
        shot('04_student_forbidden_admin.png')

        # 4. 教师端 + 审批
        context.clear_cookies()
        login('dev_teacher')
        check('教师登录后落在教师工作台', page.url.endswith('/teacher/'), page.url)
        shot('05_teacher_home.png')

        page.goto(base + '/teacher/approvals/', wait_until='domcontentloaded')
        check('教师审批页有待批请假', '待批请假' in page.content())
        shot('06_teacher_approvals.png')
        approve = page.locator(
            "form[action*='/approvals/leave/'][action*='/approve/'] button[type=submit]").first
        if approve.count():
            approve.click()
            page.wait_for_load_state('domcontentloaded')
            check('教师批准请假成功', '已批准' in page.content(), page.url)
        else:
            check('教师批准请假成功', False, '没有待批请假按钮')
        shot('07_teacher_after_approve.png')

        # 5. 学生端验证审批结果同步
        context.clear_cookies()
        login('dev_student')
        page.goto(base + '/student/attendance/', wait_until='domcontentloaded')
        check('学生端同步看到已批准', '已批准' in page.content(), page.url)
        shot('08_student_after_approval.png')

        # 6. 辅导员
        context.clear_cookies()
        login('dev_counselor')
        page.goto(base + '/teacher/', wait_until='domcontentloaded')
        check('辅导员看到辅导员菜单', '辅导员工作' in page.content())
        page.goto(base + '/teacher/classes/', wait_until='domcontentloaded')
        check('辅导员负责班级有学生', '软工2401' in page.content())
        shot('09_counselor_classes.png')

        # 7. 学院管理员
        context.clear_cookies()
        login('dev_college')
        check('学院管理员落在管理控制台', page.url.endswith('/admin/'), page.url)
        response = page.goto(base + '/admin/settings/', wait_until='domcontentloaded')
        check('学院管理员访问系统配置返回 403',
              response is not None and response.status == 403,
              response.status if response else 'no-response')
        shot('10_college_settings_denied.png')

        # 8. 超级管理员：发布公告 → 学生端可见
        context.clear_cookies()
        login('dev_admin')
        check('超管落在管理控制台', page.url.endswith('/admin/'), page.url)
        shot('11_admin_home.png')

        page.goto(base + '/admin/users/', wait_until='domcontentloaded')
        check('管理端用户列表可见', '用户账号' in page.content())
        shot('12_admin_users.png')

        title = '验收公告：三端融合验证'
        page.goto(base + '/admin/notices/', wait_until='domcontentloaded')
        page.fill('#title', title)
        page.fill('#body', '本公告由产品验收脚本发布于管理控制台，用于验证学生端可见性。')
        page.select_option('#audience', 'student')
        page.click("button:has-text('创建公告')")
        page.wait_for_load_state('domcontentloaded')
        check('管理员创建并发布公告', title in page.content(), page.url)

        page.goto(base + '/admin/settings/', wait_until='domcontentloaded')
        check('超管可访问系统配置', '系统配置与权限治理' in page.content(), page.url)
        shot('13_admin_settings.png')

        # 9. 学生端看到新公告
        context.clear_cookies()
        login('dev_student')
        page.goto(base + '/student/notices/', wait_until='domcontentloaded')
        check('学生端看到管理员发布的公告', title in page.content(), page.url)
        shot('14_student_notices.png')

        # 10. 教师端越权学生端
        context.clear_cookies()
        login('dev_teacher')
        response = page.goto(base + '/student/', wait_until='domcontentloaded')
        check('教师访问学生端返回 403',
              response is not None and response.status == 403,
              response.status if response else 'no-response')

        browser.close()

    failures = [item for item in checks if not item['ok']]
    report = {
        'base': base,
        'checks': checks,
        'console_errors': console_errors[:20],
        'failures': failures,
        'ok': not failures,
    }
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
