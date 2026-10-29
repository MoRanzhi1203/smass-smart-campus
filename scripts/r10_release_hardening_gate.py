"""H0–H9 发行加固门禁：校验任务状态**与真实证据**。

规则：
1. 结构：ID 唯一、依赖存在、无环、状态合法；
2. TESTED 必须有非空 evidence；
3. TESTED 的依赖也必须 TESTED；
4. `--strict`：全部 H0..H9 都 TESTED 才 exit 0；
5. 额外：文档清单与迁移证据检查（`--docs`）。

用法：
    conda run -n smass python scripts/r10_release_hardening_gate.py
    conda run -n smass python scripts/r10_release_hardening_gate.py --strict
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER = BASE / 'docs' / 'dsh_run' / 'R10_HARDENING_TASKS.json'

VALID = {'NOT_STARTED', 'READY', 'IN_PROGRESS', 'TESTED', 'BLOCKED', 'NOT_RUN'}

REQUIRED_DOCS = [
    'SMASS_R10_Hardening_Execution_Report.md',
    'SMASS_R10_Password_Lifecycle_Report.md',
    'SMASS_R10_Uniqueness_Enforcement_Report.md',
    'SMASS_R10_WebKit_Root_Cause.md',
    'SMASS_R10_Accessibility_Audit.md',
    'SMASS_R10_Existing_DB_Upgrade_Drill.md',
    'SMASS_R10_Security_Regression.md',
    'SMASS_R10_Release_Go_NoGo.md',
    'SMASS_R10_Hardening_Change_Log.md',
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


def check_evidence(ledger, check_docs=False):
    warnings = []
    by_id = {t['id']: t for t in ledger['tasks']}

    for task in ledger['tasks']:
        if task.get('status') != 'TESTED':
            continue
        if not (task.get('evidence') or []):
            warnings.append('{} 标 TESTED 但 evidence 为空'.format(task['id']))
        for dep in task.get('dependencies', []):
            if by_id.get(dep, {}).get('status') != 'TESTED':
                warnings.append(
                    '{} 已 TESTED 但依赖 {} 是 {}'.format(
                        task['id'], dep, by_id.get(dep, {}).get('status')))

    if check_docs:
        for name in REQUIRED_DOCS:
            if not (BASE / 'docs' / name).exists():
                warnings.append('缺少文档: docs/{}'.format(name))

    return warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--docs', action='store_true')
    args = parser.parse_args()

    ledger = load()
    tasks = ledger['tasks']

    structural = check_structure(ledger)
    warnings = check_evidence(ledger, check_docs=args.docs)

    counts = {}
    for task in tasks:
        counts[task['status']] = counts.get(task['status'], 0) + 1

    print('ledger   : {}'.format(LEDGER))
    print('baseline : {}'.format(ledger.get('baseline_sha')))
    print('tasks    : {}'.format(len(tasks)))
    for status in sorted(counts):
        print('  {:<14} {}'.format(status, counts[status]))

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
