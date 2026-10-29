"""U0–U9 门禁：校验账本结构**与证据引用**，不只看状态。

规则：
1. ID 唯一、依赖存在、无环；
2. 状态值合法；
3. **TESTED 必须有非空 evidence**（不能只标状态不给证据）；
4. TESTED 的依赖也必须 TESTED（不能跳过前置）；
5. `--strict`：全部必须 TESTED 才 exit 0。

用法：
    conda run -n smass python scripts/r10_uiux_gate.py
    conda run -n smass python scripts/r10_uiux_gate.py --strict
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER = BASE / 'docs' / 'dsh_run' / 'R10_UIUX_TASKS.json'

VALID = {
    'NOT_STARTED', 'IN_PROGRESS', 'IMPLEMENTED', 'TESTED',
    'BUSINESS_CONFIG_PENDING', 'BLOCKED', 'NOT_RUN',
}


def load():
    return json.loads(LEDGER.read_text(encoding='utf-8'))


def check_structure(ledger):
    errors = []
    tasks = ledger.get('tasks', [])

    ids = [t.get('id') for t in tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        errors.append('重复 ID: {}'.format(sorted(duplicates)))

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
            return True
        if state.get(node) == 'visiting':
            errors.append('循环依赖: {}'.format(' -> '.join(stack + [node])))
            return False
        state[node] = 'visiting'
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, stack + [node])
        state[node] = 'done'
        return True

    for node in graph:
        visit(node, [])

    return errors


def check_evidence(ledger):
    warnings = []
    for task in ledger.get('tasks', []):
        if task.get('status') != 'TESTED':
            continue
        evidence = task.get('evidence') or []
        if not evidence:
            warnings.append('{} 标 TESTED 但 evidence 为空'.format(task['id']))

        by_id = {t['id']: t for t in ledger['tasks']}
        for dep in task.get('dependencies', []):
            dep_status = by_id.get(dep, {}).get('status')
            if dep_status != 'TESTED':
                warnings.append(
                    '{} 已 TESTED 但依赖 {} 仍是 {}'.format(
                        task['id'], dep, dep_status))
    return warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()

    ledger = load()
    tasks = ledger['tasks']

    structural = check_structure(ledger)
    evidence = check_evidence(ledger)

    counts = {}
    for task in tasks:
        counts[task['status']] = counts.get(task['status'], 0) + 1

    print('ledger   : {}'.format(LEDGER))
    print('baseline : {}'.format(ledger.get('baseline_sha')))
    print('tasks    : {}'.format(len(tasks)))
    for status in sorted(counts):
        print('  {:<26} {}'.format(status, counts[status]))

    tested = counts.get('TESTED', 0)
    print('completion: {}/{} TESTED'.format(tested, len(tasks)))

    if structural:
        print('\nSTRUCTURAL ERRORS:')
        for item in structural:
            print('  - ' + item)
    if evidence:
        print('\nEVIDENCE WARNINGS:')
        for item in evidence:
            print('  - ' + item)

    unfinished = [t['id'] for t in tasks if t['status'] != 'TESTED']
    if unfinished:
        print('\nUNFINISHED ({}): {}'.format(len(unfinished), ', '.join(unfinished)))

    if structural:
        return 2
    if args.strict and (unfinished or evidence):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
