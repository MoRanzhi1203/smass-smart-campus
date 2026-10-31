#!/usr/bin/env python
"""只读 UI 探针：用 Django 测试客户端遍历产品页面，采集可验证的页面特征。

    python scripts/audit_ui_probe.py --out docs/SMASS_System_Function_Audit/inventory

不启动浏览器、不写业务数据；只读 GET 请求。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = 'smass.settings_product'


def setup():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()


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
        '/teacher/classes/', '/teacher/counselor/students/',
        '/teacher/counselor/leaves/',
    ],
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


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def analyze(html):
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return {
        'title': (title.group(1).strip() if title else ''),
        'h1': re.sub(r'<[^>]+>', '', h1.group(1)).strip() if h1 else '',
        'text_length': len(text),
        'tables': len(re.findall(r'<table\b', html)),
        'forms': len(re.findall(r'<form\b', html)),
        'empty_states': html.count('ws-empty'),
        'legacy_links': len(re.findall(r'href="/r\d', html)),
        'primary_buttons': len(re.findall(r'class="ws-btn is-primary', html)),
        'alert_count': html.count('ws-alert'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='docs/SMASS_System_Function_Audit/inventory')
    args = parser.parse_args()
    setup()
    from django.test import Client

    secret = password()
    result = {}
    for role, urls in PAGES.items():
        client = Client()
        login_name = {
            'student': 'dev_student', 'teacher': 'dev_teacher',
            'counselor': 'dev_counselor', 'admin': 'dev_admin',
        }[role]
        client.post('/login/', {'login_name': login_name, 'password': secret})
        rows = []
        for url in urls:
            response = client.get(url)
            html = response.content.decode('utf-8', 'ignore')
            item = {'url': url, 'status': response.status_code}
            item.update(analyze(html) if response.status_code == 200 else {})
            rows.append(item)
        result[role] = rows

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'ui_probe.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')

    lines = ['# UI 探针结果（脚本生成的原始数据）', '',
             '| 角色 | 页面 | HTTP | 标题 | H1 | 正文长度 | 表格 | 表单 | 空状态 | 历史链接 |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for role, rows in result.items():
        for item in rows:
            lines.append('| {} | `{}` | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
                role, item['url'], item['status'], item.get('title', ''),
                item.get('h1', ''), item.get('text_length', ''),
                item.get('tables', ''), item.get('forms', ''),
                item.get('empty_states', ''), item.get('legacy_links', '')))
    (out / 'ui_probe.md').write_text('\n'.join(lines), encoding='utf-8')

    summary = {
        role: {
            'pages': len(rows),
            'http_200': len([item for item in rows if item['status'] == 200]),
            'with_tables': len([item for item in rows if item.get('tables')]),
            'with_forms': len([item for item in rows if item.get('forms')]),
            'with_empty_state': len([item for item in rows if item.get('empty_states')]),
            'legacy_links_total': sum(item.get('legacy_links', 0) for item in rows),
            'min_text': min((item.get('text_length', 0) for item in rows), default=0),
        }
        for role, rows in result.items()
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('RESULT: PASS')


if __name__ == '__main__':
    raise SystemExit(main())
