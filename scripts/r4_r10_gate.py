"""R4–R10 强制任务门禁（标准库实现，无外部依赖）。

用法：
    python scripts/r4_r10_gate.py            # 汇总 + 退出码
    python scripts/r4_r10_gate.py --strict   # 有任何非 TESTED 的强制任务即失败

退出码：
    0  全部强制任务 TESTED（或仅剩精确登记的 BUSINESS_CONFIG_PENDING 政策任务）
    1  --strict 模式下仍有未完成任务
    2  账本结构错误（ID 重复、依赖指向不存在、违反依赖顺序）
"""
import argparse
import json
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / 'docs' / 'dsh_run' / 'R4_R10_MANDATORY_TASKS.json'

VALID_STATUS = {
    'NOT_STARTED', 'IN_PROGRESS', 'IMPLEMENTED', 'TESTED',
    'BUSINESS_CONFIG_PENDING', 'BLOCKED', 'NOT_RUN',
}

#: 允许"未 TESTED 但可接受"的终态
ACCEPTABLE_FINAL = {'TESTED', 'BUSINESS_CONFIG_PENDING'}


def load():
    if not LEDGER.exists():
        print('MISSING ledger: {}'.format(LEDGER))
        sys.exit(2)
    data = json.loads(LEDGER.read_text(encoding='utf-8'))
    tasks = data.get('tasks') or []
    return data, tasks


def validate(tasks):
    problems = []
    ids = [task.get('id') for task in tasks]

    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        problems.append('duplicate ids: {}'.format(sorted(duplicates)))

    known = set(ids)
    for task in tasks:
        if task.get('status') not in VALID_STATUS:
            problems.append('{}: invalid status {!r}'.format(task.get('id'), task.get('status')))
        for dep in task.get('dependencies') or []:
            if dep not in known:
                problems.append('{}: dependency {!r} not found'.format(task.get('id'), dep))

    # 依赖必须"先完成"：若 A 依赖 B，则 B 不应是 NOT_STARTED 而 A 已 TESTED
    by_id = {task['id']: task for task in tasks if task.get('id')}
    for task in tasks:
        if task.get('status') != 'TESTED':
            continue
        for dep in task.get('dependencies') or []:
            dep_task = by_id.get(dep)
            if dep_task and dep_task.get('status') not in ('TESTED', 'BUSINESS_CONFIG_PENDING'):
                problems.append(
                    '{} is TESTED but dependency {} is {}'.format(
                        task['id'], dep, dep_task.get('status')
                    )
                )
    return problems


def summarize(tasks):
    counts = {}
    for task in tasks:
        counts[task.get('status', 'UNKNOWN')] = counts.get(task.get('status', 'UNKNOWN'), 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--version')
    args = parser.parse_args()

    data, tasks = load()
    if args.version:
        tasks = [t for t in tasks if t.get('version') == args.version]

    problems = validate(tasks)
    counts = summarize(tasks)
    total = len(tasks)
    done = counts.get('TESTED', 0)
    pending = counts.get('BUSINESS_CONFIG_PENDING', 0)

    print('ledger   : {}'.format(LEDGER))
    print('tasks    : {}'.format(total))
    for status in sorted(counts):
        print('  {:<26} {}'.format(status, counts[status]))
    print('completion: {}/{} TESTED (+{} policy-pending)'.format(done, total, pending))

    if problems:
        print('')
        print('STRUCTURE PROBLEMS:')
        for item in problems:
            print('  - {}'.format(item))
        return 2

    unfinished = [
        task['id'] for task in tasks
        if task.get('status') not in ACCEPTABLE_FINAL
    ]
    if unfinished:
        print('')
        print('UNFINISHED ({}): {}'.format(len(unfinished), ', '.join(unfinished)))

    if args.strict and unfinished:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
