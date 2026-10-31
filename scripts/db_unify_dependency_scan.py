#!/usr/bin/env python
"""扫描产品运行链路对 app01 历史业务表的依赖（只读）。

    python scripts/db_unify_dependency_scan.py

判定：
- 运行时依赖：产品代码（排除 app01 自身、迁移、测试、脚本）中出现
  ``from app01.models``、``app01.models.``、``apps.get_model('app01'``
  或 SQL 表名 ``app01_<table>``；
- 迁移工具依赖：``scripts/`` 中允许（一次性迁移）；
- 测试依赖：``tests`` 中允许（兼容性测试）；
- 安全状态表（``app01_account_security_state``、``app01_login_device``）
  属于产品运行时必需组件，不计为"旧业务表依赖"，但单独列出。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {'.git', '.local', 'staticfiles', '__pycache__', 'node_modules',
              'media', 'private_uploads', 'logs', 'migrations'}
PATTERNS = (
    re.compile(r'from\s+app01\.models\s+import'),
    re.compile(r'\bapp01\.models\.'),
    re.compile(r"get_model\(\s*['\"]app01['\"]"),
    re.compile(r'app01_(student|teacher|admin|classes|college|major|grade|'
               r'department|classcommittee|leaguecadres|building|dormitory|'
               r'dormitorynumber|nation|position|teacherposition)\b'),
)
SAFE_TABLES = ('app01_account_security_state', 'app01_login_device')
#: 旧库兼容层：保留 app 注册与映射常量供迁移/兼容测试使用，
#: 产品代码不得 import（下方会单独校验）。
COMPAT_MODULES = ('r22_account',)


def classify(relative: Path):
    parts = relative.parts
    if parts[0] == 'app01':
        return 'app01_internal'
    if parts[0] in COMPAT_MODULES:
        return 'legacy_compat'
    if 'tests' in parts or any(part.startswith('test_') for part in parts):
        return 'test'
    if parts[0] == 'scripts':
        return 'migration_tool'
    return 'runtime'


def compat_imported_by_runtime():
    """产品代码是否 import 旧库映射层（identity/legacy_compat）。

    ``r22_account.audit`` 只写 ``AccountAuditEvent``，不读 app01 旧表，
    因此单独记为审计依赖，不算旧库依赖；配置层（settings_*/urls_*）不计。
    """
    findings = []
    audit_only = []
    pattern = re.compile(
        r'r22_account\.(identity|legacy_compat)'
        r'|from\s+r22_account\s+import\s+(identity|legacy_compat)')
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.parts[0] in ('app01',) + COMPAT_MODULES:
            continue
        if relative.parts[0] == 'scripts':
            continue
        if 'tests' in relative.parts:
            continue
        if relative.name.startswith(('settings_', 'urls_')):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:  # noqa: BLE001
            continue
        if pattern.search(text):
            findings.append(relative.as_posix())
        elif 'r22_account' in text:
            audit_only.append(relative.as_posix())
    return findings, audit_only


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    findings = []
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if relative.name == 'db_unify_dependency_scan.py':
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:  # noqa: BLE001
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(safe in line for safe in SAFE_TABLES):
                continue
            for pattern in PATTERNS:
                if pattern.search(line):
                    findings.append({
                        'file': relative.as_posix(),
                        'line': number,
                        'category': classify(relative),
                        'excerpt': line.strip()[:160],
                    })
                    break

    runtime = [item for item in findings if item['category'] == 'runtime']
    compat_imports, audit_only = compat_imported_by_runtime()
    report = {
        'findings_total': len(findings),
        'runtime_dependencies': runtime,
        'compat_imported_by_runtime': compat_imports,
        'audit_dependency_only': audit_only,
        'by_category': {
            key: len([item for item in findings
                      if item['category'] == key])
            for key in ('runtime', 'app01_internal', 'legacy_compat',
                        'migration_tool', 'test')
        },
        'ok': not runtime and not compat_imports,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
