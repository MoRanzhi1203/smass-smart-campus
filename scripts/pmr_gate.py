"""PMR 门禁：任务状态 + 证据 + 产物 + 命令日志退出码。

四层检查：
1. 结构：ID 唯一、依赖存在、无环、状态合法
2. 证据：TESTED 必须有非空 evidence；依赖也必须 TESTED
3. 产物（`--artifacts`）：12 份 PMR 文档、关键脚本、测试文件
4. 命令日志（`--commands`）：解析 `PMR_COMMAND_LOG.md` 里的退出码，
   出现非零退出即失败（防止"只写文档没真跑"）

退出码：
    0 通过
    1 strict 未全绿 / 有警告
    2 结构性错误

用法：
    conda run -n smass python scripts/pmr_gate.py
    conda run -n smass python scripts/pmr_gate.py --strict --artifacts --commands
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER = BASE / 'docs' / 'dsh_run' / 'PMR_TASKS.json'
COMMAND_LOG = BASE / 'docs' / 'dsh_run' / 'PMR_COMMAND_LOG.md'

VALID = {
    'NOT_STARTED', 'READY', 'IN_PROGRESS', 'TESTED',
    'FAILED_RETRYABLE', 'BLOCKED_EXTERNAL_AUTH', 'BLOCKED_TECHNICAL',
}

REQUIRED_DOCS = [
    'SMASS_PMR_Executive_Report.md',
    'SMASS_PMR_Legacy_Auth_Compatibility.md',
    'SMASS_PMR_Synthetic_Data_Spec.md',
    'SMASS_PMR_Row_Migration_and_Reconciliation.md',
    'SMASS_PMR_Dual_Write_Rollback.md',
    'SMASS_PMR_Upgrade_Restore_Drill.md',
    'SMASS_PMR_Performance_and_Concurrency.md',
    'SMASS_PMR_Security_and_A11y.md',
    'SMASS_PMR_Real_Data_Authorization_Package.md',
    'SMASS_PMR_Go_NoGo.md',
    'SMASS_PMR_Test_Report.md',
    'SMASS_PMR_Change_Log.md',
]

REQUIRED_SCRIPTS = [
    'scripts/pmr_gate.py',
    'scripts/pmr_synthetic_fixture.py',
    'scripts/pmr_migrate_rows.py',
    'scripts/pmr_upgrade_restore.py',
]

REQUIRED_TESTS = [
    'smass_operations/tests/test_pmr_pm1_legacy_auth.py',
    'smass_operations/tests/test_pmr_pm3_migration.py',
]


def load():
    return json.loads(LEDGER.read_text(encoding='utf-8'))


def check_structure(ledger):
    errors = []
    tasks = ledger.get('tasks', [])

    ids = [t.get('id') for t in tasks]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errors.append('重复 ID: {}'.format(sorted(dup)))

    known = set(ids)
    for task in tasks:
        for dep in task.get('dependencies', []):
            if dep not in known:
                errors.append('{} 依赖不存在的 {}'.format(task['id'], dep))
        if task.get('status') not in VALID:
            errors.append('{} 状态非法: {}'.format(task['id'], task.get('status')))

    graph = {t['id']: list(t.get('dependencies', [])) for t in tasks}
    state = {}

    def visit(node, stack):
        if state.get(node) == 'done':
            return
        if state.get(node) == 'visiting':
            errors.append('循环依赖: {}'.format(' -> '.join(stack + [node])))
            return
        state[node] = 'visiting'
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, stack + [node])
        state[node] = 'done'

    for node in graph:
        visit(node, [])

    return errors


def check_evidence(ledger):
    warnings = []
    by_id = {t['id']: t for t in ledger['tasks']}

    for task in ledger['tasks']:
        if task.get('status') != 'TESTED':
            continue
        if not (task.get('evidence') or []):
            warnings.append('{} 标 TESTED 但 evidence 为空'.format(task['id']))
        for dep in task.get('dependencies', []):
            dep_status = by_id.get(dep, {}).get('status')
            if dep_status != 'TESTED':
                warnings.append(
                    '{} 已 TESTED 但依赖 {} 是 {}'.format(task['id'], dep, dep_status))

    return warnings


def check_artifacts():
    warnings = []

    for name in REQUIRED_DOCS:
        path = BASE / 'docs' / name
        if not path.exists():
            warnings.append('缺少文档: docs/{}'.format(name))
        elif path.stat().st_size < 500:
            warnings.append('文档过短（可能占位）: docs/{}'.format(name))

    for rel in REQUIRED_SCRIPTS:
        if not (BASE / rel).exists():
            warnings.append('缺少脚本: {}'.format(rel))

    for rel in REQUIRED_TESTS:
        if not (BASE / rel).exists():
            warnings.append('缺少测试: {}'.format(rel))

    return warnings


def check_commands():
    """解析命令日志里的退出码；非零即失败。"""
    warnings = []
    if not COMMAND_LOG.exists():
        return ['缺少命令日志: docs/dsh_run/PMR_COMMAND_LOG.md']

    text = COMMAND_LOG.read_text(encoding='utf-8')
    # 期望格式：| n | command | exit | note |
    rows = re.findall(r'^\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|', text, re.M)
    if not rows:
        return ['命令日志中没有可解析的行（期望 | n | cmd | exit | note |）']

    nonzero = []
    for idx, cmd, exit_code in rows:
        code = exit_code.strip()
        if not code:
            continue
        if code not in ('0', '-', '—'):
            nonzero.append((idx.strip(), cmd.strip()[:60], code))

    if nonzero:
        for idx, cmd, code in nonzero:
            warnings.append('命令日志 #{} exit={} : {}'.format(idx, code, cmd))

    return warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--artifacts', action='store_true')
    parser.add_argument('--commands', action='store_true')
    args = parser.parse_args()

    if not LEDGER.exists():
        print('ledger missing: {}'.format(LEDGER))
        return 2

    ledger = load()
    tasks = ledger['tasks']

    structural = check_structure(ledger)
    warnings = check_evidence(ledger)
    if args.artifacts:
        warnings += check_artifacts()
    if args.commands:
        warnings += check_commands()

    counts = {}
    for task in tasks:
        counts[task['status']] = counts.get(task['status'], 0) + 1

    print('ledger   : {}'.format(LEDGER))
    print('baseline : {}'.format(ledger.get('baseline_sha')))
    print('tasks    : {}'.format(len(tasks)))
    for status in sorted(counts):
        print('  {:<24} {}'.format(status, counts[status]))

    tested = counts.get('TESTED', 0)
    print('completion: {}/{} TESTED'.format(tested, len(tasks)))

    if structural:
        print('\nSTRUCTURAL ERRORS:')
        for item in structural:
            print('  - ' + item)
    if warnings:
        print('\nWARNINGS:')
        for item in warnings:
            print('  - ' + item)

    unfinished = [t['id'] for t in tasks if t['status'] != 'TESTED']
    if unfinished:
        print('\nUNFINISHED ({}): {}'.format(len(unfinished), ', '.join(unfinished)))

    if structural:
        return 2
    if args.strict and (unfinished or warnings):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
