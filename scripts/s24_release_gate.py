#!/usr/bin/env python
"""S24 发布门禁：一条命令跑完全部放行检查。

用法::

    python scripts/s24_release_gate.py                  # 完整门禁（含测试套件）
    python scripts/s24_release_gate.py --quick          # 跳过测试套件（本地快检）
    python scripts/s24_release_gate.py --allow-dirty    # 开发中：允许工作区脏
    python scripts/s24_release_gate.py --json out.json
    python scripts/s24_release_gate.py --self-test

门禁项
------
1. ``git-clean``：工作区无未提交改动；
2. ``git-remote-sync``：HEAD 与远端分支一致；
3. ``admission``：仓库准入检查（``scripts/repo_admission_check.py``）；
4. ``secret-scan``：凭据扫描（``scripts/r9_secret_scan.py``）；
5. ``deps``：依赖锁定与基线（``scripts/s20_dependency_audit.py``）；
6. ``controls``：安全控制点矩阵（``scripts/s21_incident_drill.py --matrix-only``）；
7. ``migrations``：无未生成的模型迁移；
8. ``security-suite``：S18 跨模块负向测试集；
9. ``session-suite``：S17 会话安全测试；
10. ``mfa-suite``：S09 特权 MFA 测试；
11. ``ledger``：任务账本统计（只报告，不阻断）。

任一 ``fail`` 即门禁 FAIL；``skip`` 不影响结论但会在报告中标注。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(command, timeout=1800, cwd=ROOT):
    started = time.time()
    try:
        completed = subprocess.run(  # noqa: S603 - 固定参数
            command, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout)
    except subprocess.SubprocessError as exc:
        return {'ok': False, 'code': -1, 'seconds': round(time.time() - started, 2),
                'output': str(exc)}
    output = (completed.stdout or '') + (completed.stderr or '')
    return {
        'ok': completed.returncode == 0,
        'code': completed.returncode,
        'seconds': round(time.time() - started, 2),
        'output': output,
    }


def last_line(text):
    lines = [item.strip() for item in str(text).splitlines() if item.strip()]
    return lines[-1][:200] if lines else ''


def check_git_clean(allow_dirty):
    if allow_dirty:
        return {'status': 'skip', 'detail': '--allow-dirty：跳过工作区检查'}
    outcome = run(['git', 'status', '--porcelain=v1', '-uall'], timeout=120)
    dirty = [line for line in outcome['output'].splitlines() if line.strip()]
    return {'status': 'pass' if not dirty else 'fail',
            'detail': '工作区干净' if not dirty else '未提交改动：{} 个文件'.format(len(dirty))}


def check_remote_sync():
    branch = run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], timeout=120)
    name = branch['output'].strip()
    if not name or name == 'HEAD':
        return {'status': 'fail', 'detail': '无法确定当前分支（detached HEAD）'}
    head = run(['git', 'rev-parse', 'HEAD'], timeout=120)['output'].strip()
    remote = run(['git', 'ls-remote', 'origin', 'refs/heads/{}'.format(name)],
                 timeout=300)
    if not remote['ok'] or not remote['output'].strip():
        return {'status': 'fail', 'detail': '无法读取远端分支 {}'.format(name)}
    remote_sha = remote['output'].split()[0]
    return {
        'status': 'pass' if head == remote_sha else 'fail',
        'detail': '{} 本地 {} 远端 {}'.format(
            name, head[:12], remote_sha[:12]) if head == remote_sha
        else '{} 本地 {} != 远端 {}'.format(name, head[:12], remote_sha[:12]),
    }


def check_script(label, args, timeout=1800):
    outcome = run([PY] + args, timeout=timeout)
    return {'status': 'pass' if outcome['ok'] else 'fail',
            'detail': last_line(outcome['output']),
            'seconds': outcome['seconds']}


def check_migrations():
    outcome = run([PY, 'manage.py', 'makemigrations', '--check', '--dry-run',
                   '--settings=smass.settings_r22'], timeout=600)
    detected = 'No changes detected' in outcome['output']
    return {'status': 'pass' if outcome['ok'] and detected else 'fail',
            'detail': '无未生成迁移' if detected else last_line(outcome['output'])}


def check_suite(label, app, settings, timeout=1800):
    outcome = run([PY, 'manage.py', 'test', app, '--settings={}'.format(settings),
                   '--noinput', '--verbosity=1'], timeout=timeout)
    match = re.search(r'Ran (\d+) tests?', outcome['output'])
    ran = int(match.group(1)) if match else 0
    ok = outcome['ok'] and ran > 0 and 'OK' in outcome['output']
    return {'status': 'pass' if ok else 'fail',
            'detail': '{} 例 {}'.format(ran, 'OK' if ok else 'FAILED'),
            'seconds': outcome['seconds']}


def ledger_stats():
    path = ROOT.parent / 'agent-sessions' / 'dsh_run' / \
        'SMART_CAMPUS_MASTER_TASKS.json'
    if not path.is_file():
        return {'status': 'skip', 'detail': '账本文件不存在'}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'status': 'skip', 'detail': '账本无法解析'}
    counts = {}
    for task in data.get('tasks', []):
        counts[task.get('state', 'UNKNOWN')] = counts.get(
            task.get('state', 'UNKNOWN'), 0) + 1
    return {'status': 'pass' if counts.get('BLOCKED', 0) == 0 else 'fail',
            'detail': ' / '.join('{} {}'.format(k, v) for k, v in sorted(counts.items()))}


def gate(quick=False, allow_dirty=False, with_pip_audit=False):
    report = {'started_utc': datetime.now(dt_timezone.utc).isoformat(),
              'checks': []}

    def add(name, result):
        result['name'] = name
        report['checks'].append(result)

    add('git-clean', check_git_clean(allow_dirty))
    add('git-remote-sync', check_remote_sync())
    add('admission', check_script('admission',
                                  ['scripts/repo_admission_check.py'], 600))
    add('secret-scan', check_script('secret-scan',
                                    ['scripts/r9_secret_scan.py'], 600))
    deps_args = ['scripts/s20_dependency_audit.py', '--no-regenerate']
    if not with_pip_audit:
        deps_args.append('--skip-pip-audit')
    add('deps', check_script('deps', deps_args, 900))
    add('controls', check_script('controls',
                                 ['scripts/s21_incident_drill.py', '--matrix-only'], 600))
    add('migrations', check_migrations())

    if quick:
        for name in ('security-suite', 'session-suite', 'mfa-suite'):
            add(name, {'status': 'skip', 'detail': '--quick 跳过'})
    else:
        add('security-suite', check_suite(
            'security-suite', 'smass_security_tests', 'smass.settings_security'))
        add('session-suite', check_suite(
            'session-suite', 'app01.tests.test_s17_session_security',
            'smass.settings_r22'))
        add('mfa-suite', check_suite(
            'mfa-suite', 'smass_mfa', 'smass.settings_s09'))

    add('ledger', ledger_stats())

    failed = [item for item in report['checks'] if item['status'] == 'fail']
    report['failed'] = [item['name'] for item in failed]
    report['ok'] = not failed
    report['finished_utc'] = datetime.now(dt_timezone.utc).isoformat()
    return report


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(last_line('a\n\nb\n') == 'b', 'last_line 取最后非空行')
    check(last_line('') == '', 'last_line 空输入')
    verdict = gate(quick=True, allow_dirty=True)
    check(any(item['name'] == 'git-clean' and item['status'] == 'skip'
              for item in verdict['checks']), 'allow_dirty 时 git-clean 记为 skip')
    check(all('detail' in item for item in verdict['checks']), '每项都有 detail')
    check(isinstance(verdict['ok'], bool), 'ok 为布尔值')

    for message in failures:
        print('SELF-TEST FAIL:', message)
    if not failures:
        print('SELF-TEST PASS (5 checks)')
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description='S24 发布门禁')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--allow-dirty', action='store_true')
    parser.add_argument('--with-pip-audit', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    report = gate(quick=args.quick, allow_dirty=args.allow_dirty,
                  with_pip_audit=args.with_pip_audit)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(text, encoding='utf-8')

    for item in report['checks']:
        print('[{:4}] {:18} {}'.format(item['status'].upper(), item['name'],
                                       item.get('detail', '')))
    print('GATE:', 'PASS' if report['ok'] else 'FAIL')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
