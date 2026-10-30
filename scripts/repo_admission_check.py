#!/usr/bin/env python
"""仓库准入检查（RH4）。

用途
----
阻止不应进入 Git 的内容：本地研发资料（``.local/``）、根目录提示词、
Agent 运行账本与截图、个人笔记、凭据、日志、数据库/Git 备份、超大文件。

检查范围（默认全部）：
1. **索引**（``git ls-files``）——当前被跟踪的文件；
2. **暂存区**（``git diff --cached --name-only``）——即将提交的改动；
3. **HEAD 树**（``git ls-tree -r HEAD``）——即将被 push 的内容。

这样即使有人用 ``git add -f`` 绕过 ``.gitignore``，也会在这里被拦住；
只扫工作区或只看 ``.gitignore`` 都不够。

用法::

    python scripts/repo_admission_check.py            # 检查，失败返回 1
    python scripts/repo_admission_check.py --selftest # 自测：合成违规文件必须被检出
    python scripts/repo_admission_check.py --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

#: (正则, 类别, 说明)。路径一律使用 / 分隔的相对路径。
FORBIDDEN = [
    (r'^\.local/', 'local-research', '本地研发资料目录，禁止入库'),
    (r'^SMASS_[^/]*\.md$', 'root-prompt', '根目录提示词/计划文档，禁止入库'),
    (r'^docs/dsh_run/', 'agent-ledger', 'Agent 运行账本，禁止入库'),
    (r'^docs/screenshots/', 'agent-screenshot', '开发过程截图，禁止入库'),
    (r'^note/', 'personal-note', '个人开发笔记，禁止入库'),
    (r'(?i)(^|/)\.env$', 'credential', '环境变量文件含凭据'),
    (r'(?i)(^|/)\.env\.(?!example$)[^/]+$', 'credential', '环境变量变体'),
    (r'(?i)\.(pem|key|p12|pfx)$', 'credential', '私钥/证书文件'),
    (r'(?i)(^|/)id_(rsa|ed25519)$', 'credential', 'SSH 私钥'),
    (r'(?i)\.(dump|bundle|bak)$', 'backup', '数据库/Git 备份'),
    (r'(?i)\.sql\.gz$', 'backup', '压缩 SQL 备份'),
    (r'^logs/', 'log', '运行日志目录'),
    (r'(?i)\.log$', 'log', '日志文件'),
    (r'^media/uploads/', 'upload', '用户上传目录'),
    (r'(?i)(^|/)__pycache__/', 'cache', 'Python 缓存'),
    (r'(?i)\.py[co]$', 'cache', 'Python 字节码'),
    (r'(?i)(^|/)\.pytest_cache/', 'cache', 'pytest 缓存'),
]

#: 显式允许（即使命中上面规则）。仅用于有据可查的例外。
ALLOW = {
    '.env.example': '脱敏配置样例，可公开',
    'media/head_sculpture/profile-img.jpg': '模板引用的默认头像',
}

#: 单文件大小上限（字节）
MAX_FILE_BYTES = 5 * 1024 * 1024


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(['git', *args], cwd=str(BASE),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode('utf-8', 'replace')


def compile_rules():
    import re
    return [(re.compile(rx), cat, why) for rx, cat, why in FORBIDDEN]


def check_paths(paths, rules=None):
    """返回问题列表 ``[{path, category, reason}]``。"""
    import re
    rules = rules if rules is not None else compile_rules()
    problems = []
    for path in paths:
        rel = path.replace('\\', '/')
        if rel in ALLOW:
            continue
        for rx, cat, why in rules:
            if rx.search(rel):
                problems.append({'path': rel, 'category': cat, 'reason': why})
                break
    return problems


def huge_files(paths):
    problems = []
    for path in paths:
        p = BASE / path
        try:
            if p.is_file() and p.stat().st_size > MAX_FILE_BYTES:
                problems.append({
                    'path': path.replace('\\', '/'),
                    'category': 'large-file',
                    'reason': '超过 {} MB'.format(MAX_FILE_BYTES // 1024 // 1024),
                    'size': p.stat().st_size,
                })
        except OSError:
            continue
    return problems


def collect(include_head: bool = False):
    """收集待检查路径。

    默认只查 ``index``（当前跟踪）与 ``staged``（即将提交）——这是提交前的
    实际风险面。``--head`` 额外检查 HEAD 树，用于确认"已提交内容"干净。
    """
    _, index = git('ls-files')
    _, staged = git('diff', '--cached', '--name-only', '--diff-filter=ACMR')
    sources = {
        'index': [l for l in index.splitlines() if l.strip()],
        'staged': [l for l in staged.splitlines() if l.strip()],
    }
    if include_head:
        rc, head = git('ls-tree', '-r', '--name-only', 'HEAD')
        sources['head'] = [l for l in head.splitlines() if l.strip()] if rc == 0 else []
    return sources


def report(as_json: bool, include_head: bool = False) -> int:
    sources = collect(include_head=include_head)
    findings = {}
    total = 0
    for name, paths in sources.items():
        probs = check_paths(paths) + huge_files(paths)
        findings[name] = probs
        total += len(probs)

    if as_json:
        print(json.dumps({'ok': total == 0, 'problems': findings,
                          'scanned': {k: len(v) for k, v in sources.items()}},
                         ensure_ascii=False, indent=2))
    else:
        for name, probs in findings.items():
            status = 'OK' if not probs else 'FAIL({})'.format(len(probs))
            print('[{}] {:<8} scanned={}'.format(status, name, len(sources[name])))
            for p in probs[:40]:
                print('    - {:<60} [{}] {}'.format(p['path'], p['category'], p['reason']))
            if len(probs) > 40:
                print('    ... 以及另外 {} 条'.format(len(probs) - 40))
        print()
        print('TOTAL problems: {}'.format(total))
        print('RESULT: {}'.format('PASS' if total == 0 else 'FAIL'))
    return 0 if total == 0 else 1


def selftest() -> int:
    """用合成路径验证规则确实会拦截，且合法路径不会被误拦。"""
    must_fail = [
        '.local/agent-sessions/x.json',
        'SMASS_Master_Development_DSH_Prompt.md',
        'docs/dsh_run/TASKS.json',
        'docs/screenshots/a.png',
        'note/log.md',
        '.env',
        '.env.production',
        'certs/server.key',
        'secrets/app.pem',
        'backup/db.dump',
        'archive.bundle',
        'logs/app.log',
        'media/uploads/photo.jpg',
        'app01/__pycache__/models.cpython-312.pyc',
    ]
    must_pass = [
        'app01/models.py',
        'smass/settings.py',
        'docs/SMASS_R11_Scheduling.md',
        'scripts/smart_campus_gate.py',
        'templates/r11/plan.html',
        'static/plugins/bootstrap-5.3.2/js/bootstrap.bundle.js',
        '.env.example',
        'media/head_sculpture/profile-img.jpg',
        'smass_data_exchange/tests/test_s25_r5.py',
        'docs/SMASS_Technical_Decisions.md',
    ]

    failures = []
    bad = check_paths(must_fail)
    caught = {p['path'] for p in bad}
    for path in must_fail:
        if path not in caught:
            failures.append('MISSED (should be blocked): ' + path)

    leaked = check_paths(must_pass)
    for p in leaked:
        failures.append('FALSE POSITIVE (should pass): {} [{}]'.format(
            p['path'], p['category']))

    print('selftest: must_fail={} must_pass={}'.format(len(must_fail), len(must_pass)))
    if failures:
        for f in failures:
            print('  FAIL ' + f)
        print('SELFTEST: FAIL')
        return 1
    print('SELFTEST: PASS')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='SMASS 仓库准入检查')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--head', action='store_true',
                    help='额外检查 HEAD 树（确认已提交内容干净）')
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return report(args.json, include_head=args.head)


if __name__ == '__main__':
    raise SystemExit(main())
