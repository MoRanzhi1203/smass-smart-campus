"""H8：全量回归测量（不硬编码总数，实际跑一遍并统计）。

用法：
    conda run -n smass python scripts/r10_full_regression.py
    conda run -n smass python scripts/r10_full_regression.py --json
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

SUITES = [
    ('smass_operations', 'smass.settings_r10'),
    ('smass_analytics', 'smass.settings_r7'),
    ('smass_organization', 'smass.settings_r4'),
    ('smass_academic', 'smass.settings_r5'),
    ('smass_workflow', 'smass.settings_r6'),
    ('smass_api', 'smass.settings_r8'),
    ('r22_account', 'smass.settings_r22'),
    ('r21_account', 'smass.settings_r21'),
    ('app01', None),
    ('tests_e2e', None),
]

RAN_RE = re.compile(r'^Ran (\d+) tests? in ([\d.]+)s', re.M)
FAILED_RE = re.compile(r'^FAILED \((.*)\)', re.M)


def run_suite(name, settings_name):
    cmd = [PYTHON, 'manage.py', 'test', name, '-v', '1']
    if settings_name:
        cmd.append('--settings={}'.format(settings_name))

    started = time.perf_counter()
    result = subprocess.run(
        cmd, cwd=str(BASE), capture_output=True, text=True,
        # 子进程输出为 UTF-8（含中文用例名）。Windows 默认按 GBK 解码会抛
        # UnicodeDecodeError，导致统计为 0 并把通过的套件误判为失败。
        encoding='utf-8', errors='replace',
    )
    elapsed = round(time.perf_counter() - started, 1)
    output = (result.stdout or '') + (result.stderr or '')

    ran_match = RAN_RE.search(output)
    count = int(ran_match.group(1)) if ran_match else 0

    failed_match = FAILED_RE.search(output)
    failed_detail = failed_match.group(1) if failed_match else ''

    return {
        'suite': name,
        'settings': settings_name or 'formal',
        'count': count,
        'exit': result.returncode,
        'ok': result.returncode == 0,
        'seconds': elapsed,
        'failed_detail': failed_detail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    results = []
    for name, settings_name in SUITES:
        item = run_suite(name, settings_name)
        results.append(item)
        status = 'OK' if item['ok'] else 'FAILED'
        print('{:<20} {:<22} {:>4} tests  {:>6}s  {}'.format(
            item['suite'], item['settings'], item['count'],
            item['seconds'], status))
        if not item['ok'] and item['failed_detail']:
            print('    -> {}'.format(item['failed_detail']))

    total = sum(item['count'] for item in results)
    failed = [item for item in results if not item['ok']]

    print()
    print('TOTAL tests measured : {}'.format(total))
    print('suites               : {} (failed: {})'.format(
        len(results), len(failed)))
    print('all green            : {}'.format(not failed))

    if args.json:
        print(json.dumps({
            'total': total,
            'suites': len(results),
            'failed': [f['suite'] for f in failed],
            'results': results,
        }, ensure_ascii=False, indent=2))

    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
