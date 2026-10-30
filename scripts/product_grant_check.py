#!/usr/bin/env python
"""验证「管理员配置 → 授权用户可见」的端到端一致性。

步骤：
1. 超管在管理控制台给某学生账号授予 ``teacher`` 角色；
2. 该用户重新登录，落地页必须从学生工作台变为教师工作台；
3. 超管撤销角色后，落地页恢复为学生工作台。

只操作隔离库 ``smass_product_dev``，结束后恢复原角色集合。
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

    from r21_account.models import Account

    secret = password()
    target = Account.objects.get(login_name='dev_student2')
    admin = Account.objects.get(login_name='dev_admin')
    checks = []

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    student_client = Client()
    student_client.post('/login/', {'login_name': 'dev_student2',
                                   'password': secret})
    response = student_client.get('/')
    check('授予前落地学生工作台',
          response.status_code == 302 and response.headers.get(
              'Location') == '/student/', response.headers.get('Location'))

    admin_client = Client()
    admin_client.post('/login/', {'login_name': 'dev_admin',
                                 'password': secret})
    response = admin_client.post(
        '/admin/users/{}/role/'.format(target.pk),
        {'action': 'grant', 'role': 'teacher'})
    check('管理控制台授予教师角色', response.status_code == 302, response.status_code)

    target.refresh_from_db()
    check('角色已生效', 'teacher' in set(target.active_roles()),
          sorted(target.active_roles()))

    relogin = Client()
    relogin.post('/login/', {'login_name': 'dev_student2', 'password': secret})
    response = relogin.get('/')
    check('授予后落地教师工作台',
          response.status_code == 302 and response.headers.get(
              'Location') == '/teacher/', response.headers.get('Location'))
    response = relogin.get('/teacher/')
    check('授予后可访问教师工作台', response.status_code == 200,
          response.status_code)

    response = admin_client.post(
        '/admin/users/{}/role/'.format(target.pk),
        {'action': 'revoke', 'role': 'teacher'})
    check('管理控制台撤销角色', response.status_code == 302, response.status_code)

    target.refresh_from_db()
    check('角色已撤销', 'teacher' not in set(target.active_roles()),
          sorted(target.active_roles()))

    restored = Client()
    restored.post('/login/', {'login_name': 'dev_student2', 'password': secret})
    response = restored.get('/')
    check('撤销后恢复学生工作台',
          response.status_code == 302 and response.headers.get(
              'Location') == '/student/', response.headers.get('Location'))

    failures = [item for item in checks if not item['ok']]
    report = {'checks': checks, 'failures': failures, 'ok': not failures}
    path = ROOT / '.local/evidence/product/grant_check.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
