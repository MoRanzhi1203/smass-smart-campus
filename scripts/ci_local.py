"""R9-02：本地 CI（不推送远程、不改生产）。

依次执行：
1. Django ``check``
2. ``makemigrations --check --dry-run``（正式 + 隔离配置）
3. 秘密扫描（R9-04）
4. 依赖审计（pip-audit，若已安装）
5. 各模块测试（可选，``--with-tests``）

用法：
    conda run -n smass python scripts/ci_local.py
    conda run -n smass python scripts/ci_local.py --with-tests
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

SETTINGS_LIST = [
    ('formal', None),
    ('r4', 'smass.settings_r4'),
    ('r9', 'smass.settings_r9'),
]

TEST_TARGETS = [
    ('smass_organization', 'smass.settings_r4'),
    ('smass_academic', 'smass.settings_r5'),
    ('smass_workflow', 'smass.settings_r6'),
    ('smass_analytics', 'smass.settings_r7'),
    ('smass_api', 'smass.settings_r8'),
    ('smass_operations', 'smass.settings_r9'),
]


def run(cmd, label):
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True)
    elapsed = round(time.perf_counter() - started, 2)
    ok = result.returncode == 0
    return {
        'label': label,
        'ok': ok,
        'exit': result.returncode,
        'seconds': elapsed,
        'tail': (result.stdout or result.stderr or '').strip().splitlines()[-3:],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-tests', action='store_true')
    args = parser.parse_args()

    steps = []

    steps.append(run([PYTHON, 'manage.py', 'check'], 'django check (formal)'))

    for name, settings in SETTINGS_LIST:
        cmd = [PYTHON, 'manage.py', 'makemigrations', '--check', '--dry-run']
        if settings:
            cmd.append('--settings={}'.format(settings))
        steps.append(run(cmd, 'migrations check ({})'.format(name)))

    steps.append(run([PYTHON, 'scripts/r9_secret_scan.py'], 'secret scan'))

    # pip-audit 依赖可能未安装：失败时标记 skip 而非 fail
    audit = run([PYTHON, '-m', 'pip_audit', '-r', 'requirements.txt',
                 '--progress-spinner', 'off'], 'pip-audit')
    if not audit['ok'] and 'No module named' in ' '.join(audit['tail']):
        audit['skipped'] = True
        audit['ok'] = True
    steps.append(audit)

    if args.with_tests:
        for target, settings in TEST_TARGETS:
            steps.append(run(
                [PYTHON, 'manage.py', 'test', target, '--settings={}'.format(settings)],
                'tests {}'.format(target),
            ))

    failed = [step for step in steps if not step['ok']]
    report = {
        'ok': not failed,
        'steps': steps,
        'failed': [step['label'] for step in failed],
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
