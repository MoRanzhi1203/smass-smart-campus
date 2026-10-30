#!/usr/bin/env python
"""S21 安全事件响应演练（控制点矩阵 + 负向测试实测）。

用法::

    python scripts/s21_incident_drill.py            # 矩阵 + 演练
    python scripts/s21_incident_drill.py --matrix-only
    python scripts/s21_incident_drill.py --json out.json
    python scripts/s21_incident_drill.py --self-test

阶段
----
1. **控制点矩阵**：逐条核对 runbook 中登记的检测/阻断控制点是否有代码与配置落地；
2. **负向演练**：真实执行 S18 跨模块安全测试集、S17 会话安全测试、S09 特权 MFA 测试，
   记录通过数与耗时（响应能力实证）；
3. 输出 JSON 供 S24 发布门禁与最终交付引用。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 控制点：id、名称、必须存在的文件、必须出现的符号、对应负向测试
CONTROLS = [
    {
        'id': 'CTL-01', 'name': '统一认证与会话安全',
        'files': ['app01/services/session_security.py',
                  'app01/middleware/session_security.py'],
        'symbols': ['revoke_other_devices', 'SessionSecurityMiddleware'],
        'test': ['app01.tests.test_s17_session_security', 'smass.settings_r22'],
    },
    {
        'id': 'CTL-02', 'name': '特权角色强制 MFA',
        'files': ['smass_mfa/services.py', 'smass_mfa/middleware.py'],
        'symbols': ['verify_totp', 'MfaRequiredMiddleware'],
        'test': ['smass_mfa', 'smass.settings_s09'],
    },
    {
        'id': 'CTL-03', 'name': '敏感操作双人审批',
        'files': ['smass_stepup/services.py'],
        'symbols': ['SELF_APPROVAL_DENIED', 'PAYLOAD_TAMPERED'],
        'test': None,
    },
    {
        'id': 'CTL-04', 'name': '审计与告警（哈希链）',
        'files': ['smass_audit/models.py', 'smass_audit/services.py'],
        'symbols': ['hash', 'append'],
        'test': None,
    },
    {
        'id': 'CTL-05', 'name': '字段级策略授权',
        'files': ['smass_policy/services.py'],
        'symbols': ['read_field', 'effective_fields'],
        'test': None,
    },
    {
        'id': 'CTL-06', 'name': '数据最小化与披露留痕',
        'files': ['smass_privacy/services.py'],
        'symbols': ['minimized_rows', 'DisclosureLog'],
        'test': None,
    },
    {
        'id': 'CTL-07', 'name': 'API 令牌/scope/限流/防重放',
        'files': ['smass_api_security/decorators.py',
                  'smass_api_security/services.py'],
        'symbols': ['api_endpoint', 'check_replay', 'check_rate'],
        'test': None,
    },
    {
        'id': 'CTL-08', 'name': '上传文件安全',
        'files': ['smass_uploads/services.py'],
        'symbols': ['validate', 'sanitize_filename'],
        'test': None,
    },
    {
        'id': 'CTL-09', 'name': '跨模块负向测试集',
        'files': ['smass_security_tests/tests'],
        'symbols': [],
        'test': ['smass_security_tests', 'smass.settings_security'],
    },
    {
        'id': 'CTL-10', 'name': '依赖补丁基线',
        'files': ['requirements.lock.txt', 'scripts/s20_dependency_audit.py'],
        'symbols': ['MINIMUM_VERSIONS'],
        'test': None,
    },
]


def _read(path):
    try:
        return (ROOT / path).read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return ''


def _dir_has_files(path):
    target = ROOT / path
    if not target.exists():
        return False
    if target.is_file():
        return True
    return any(item.is_file() for item in target.rglob('*.py'))


def check_controls():
    results = []
    for control in CONTROLS:
        missing_files = [item for item in control['files']
                         if not _dir_has_files(item)]
        blob = '\n'.join(_read(item) for item in control['files'] if (ROOT / item).is_file())
        if not blob:
            for item in control['files']:
                target = ROOT / item
                if target.is_dir():
                    blob += '\n'.join(
                        child.read_text(encoding='utf-8', errors='ignore')
                        for child in target.rglob('*.py'))
        missing_symbols = [item for item in control['symbols']
                           if item not in blob]
        ok = not missing_files and not missing_symbols
        results.append({
            'id': control['id'], 'name': control['name'], 'ok': ok,
            'missing_files': missing_files, 'missing_symbols': missing_symbols,
        })
    return results


def run_test(label, args, timeout=1800):
    command = [sys.executable, 'manage.py', 'test'] + list(args) + ['--noinput',
                                                                    '--verbosity=1']
    started = time.time()
    try:
        completed = subprocess.run(  # noqa: S603 - 固定参数
            command, cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout)
    except subprocess.SubprocessError as exc:
        return {'label': label, 'ok': False, 'ran': 0,
                'seconds': round(time.time() - started, 2), 'error': str(exc)}
    output = (completed.stdout or '') + (completed.stderr or '')
    match = re.search(r'Ran (\d+) tests?', output)
    ran = int(match.group(1)) if match else 0
    ok = completed.returncode == 0 and ran > 0 and 'OK' in output
    return {
        'label': label, 'ok': ok, 'ran': ran,
        'seconds': round(time.time() - started, 2),
        'tail': output.strip().splitlines()[-1] if output.strip() else '',
    }


def exercise(controls):
    plan = []
    for control in CONTROLS:
        if control['test']:
            plan.append((control['id'], control['test']))
    results = []
    for control_id, (label, settings) in plan:
        outcome = run_test(label, [label, '--settings={}'.format(settings)])
        outcome['control'] = control_id
        results.append(outcome)
    return results


def drill(matrix_only=False):
    controls = check_controls()
    report = {
        'controls': controls,
        'controls_ok': all(item['ok'] for item in controls),
        'exercise': [],
    }
    if not matrix_only:
        report['exercise'] = exercise(controls)
    report['exercise_ok'] = all(item['ok'] for item in report['exercise'])
    report['ok'] = report['controls_ok'] and report['exercise_ok']
    return report


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(_dir_has_files('app01/services/session_security.py'), '已知文件存在')
    check(not _dir_has_files('app01/services/__not_exists__.py'), '不存在的文件返回 False')
    check('MfaRequiredMiddleware' in _read('smass_mfa/middleware.py'), '符号检索命中')
    check('__NOT_A_SYMBOL__' not in _read('smass_mfa/middleware.py'), '符号检索不误报')
    check(len(CONTROLS) == 10, '控制点数量为 10')
    check(all('id' in item and 'name' in item for item in CONTROLS), '控制点字段完整')

    for message in failures:
        print('SELF-TEST FAIL:', message)
    if not failures:
        print('SELF-TEST PASS ({} checks)'.format(6))
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description='S21 安全事件响应演练')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--matrix-only', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    report = drill(matrix_only=args.matrix_only)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(text, encoding='utf-8')

    print('控制点矩阵：')
    for item in report['controls']:
        print('  [{:4}] {} {}'.format('PASS' if item['ok'] else 'FAIL',
                                      item['id'], item['name']))
        if not item['ok']:
            print('         missing files={} symbols={}'.format(
                item['missing_files'], item['missing_symbols']))
    if report['exercise']:
        print('负向演练：')
        for item in report['exercise']:
            print('  [{:4}] {} ran={} {:.1f}s'.format(
                'PASS' if item['ok'] else 'FAIL', item['label'], item['ran'],
                item['seconds']))
    print('RESULT:', 'PASS' if report['ok'] else 'FAIL')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
