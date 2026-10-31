#!/usr/bin/env python
"""A02 权限一致性审计（只读）：对比 RBAC 矩阵、产品守卫与深层 has_action。

    python scripts/rbac_consistency_check.py --json out.json

输出：
- 4 角色 × 动作的 RBAC 授权矩阵；
- 产品视图守卫使用统计（require_kind / require_system_admin）；
- 深层代码中 has_action 的调用点；
- 已知差异与风险等级（不修改任何代码）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRODUCT_DIR = ROOT / 'smass_workspace' / 'views'
SKIP_PARTS = {'.git', '.local', 'staticfiles', '__pycache__', 'migrations',
              'node_modules', 'media', 'private_uploads', 'scripts'}
DEEP_SKIP = {'smass_workspace', 'r21_account', 'r22_account', 'app01', 'scripts'}


def rbac_matrix():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smass.settings_product'
    import django

    django.setup()
    from r21_account import permissions as perms

    roles = {}
    for role, codes in perms.ROLE_PERMISSIONS.items():
        roles[str(role)] = sorted(codes)
    actions = list(perms.ACTION_CODENAMES)
    return {'roles': roles, 'actions': actions}


def product_guards():
    stats = {}
    for path in PRODUCT_DIR.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        stats[path.name] = {
            'require_kind': text.count('require_kind('),
            'require_system_admin': text.count('require_system_admin'),
            'require_recent_auth': text.count('require_recent_auth'),
            'has_action': text.count('has_action('),
        }
    return stats


def deep_has_action():
    findings = []
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.parts[0] in DEEP_SKIP:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:  # noqa: BLE001
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if 'has_action(' in line:
                findings.append({'file': relative.as_posix(),
                                 'line': number,
                                 'excerpt': line.strip()[:120]})
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    rbac = rbac_matrix()
    guards = product_guards()
    deep = deep_has_action()

    college = set(rbac['roles'].get('college_admin', []))
    system = set(rbac['roles'].get('system_admin', []))
    write_codes = {'add_data', 'change_data', 'import_data'}
    differences = []

    if college & write_codes:
        differences.append({
            'kind': 'product_stricter',
            'detail': '学院管理员在 RBAC 持有 {}，但产品端建课/建班/场地/活动/公告'
                      '要求 require_system_admin；产品比 RBAC 更严'.format(
                          sorted(college & write_codes)),
            'risk': 'low',
        })
    if deep:
        differences.append({
            'kind': 'deep_wider',
            'detail': '深层代码仍有 {} 处 has_action 判定，可能按 add/change 放行'
                      '学院管理员，与产品入口不一致'.format(len(deep)),
            'risk': 'medium',
        })
    if 'dangerous_bulk_delete' not in system:
        differences.append({
            'kind': 'no_role_has_bulk_delete',
            'detail': 'dangerous_bulk_delete 未授予任何角色（含系统管理员）',
            'risk': 'low',
        })

    report = {
        'rbac': rbac,
        'product_guards': guards,
        'deep_has_action': deep[:120],
        'deep_has_action_count': len(deep),
        'differences': differences,
        'ok': True,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(json.dumps({
        'roles': {role: len(codes) for role, codes in rbac['roles'].items()},
        'product_guards': guards,
        'deep_has_action_count': len(deep),
        'differences': differences,
    }, ensure_ascii=False, indent=2))
    print('RESULT: PASS')


if __name__ == '__main__':
    raise SystemExit(main())
