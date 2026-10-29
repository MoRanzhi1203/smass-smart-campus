"""R10 发行加固门禁：校验任务状态、证据与必要产物。

三层检查：
1. **结构**：ID 唯一、依赖存在、无环、状态合法
2. **证据**：TESTED 必须有非空 evidence；依赖也必须 TESTED
3. **产物**（`--artifacts`）：关键文件必须真实存在
   - 9 份必需文档
   - 关键测试文件
   - H2 迁移文件
   - 截图目录与数量

退出码：
    0  通过（strict 模式下要求全部 TESTED 且无警告）
    1  strict 模式下未全部 TESTED / 有警告
    2  结构性错误（无论是否 strict）

用法：
    conda run -n smass python scripts/r10_release_hardening_gate.py
    conda run -n smass python scripts/r10_release_hardening_gate.py --strict
    conda run -n smass python scripts/r10_release_hardening_gate.py --strict --artifacts
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
    'SMASS_R10_E2E_Cross_Browser.md',
    'SMASS_R10_Release_Go_NoGo.md',
    'SMASS_R10_Hardening_Change_Log.md',
]

REQUIRED_TEST_FILES = [
    'smass_operations/tests/test_r10_h1_password.py',
    'smass_operations/tests/test_r10_h2_uniqueness.py',
    'smass_operations/tests/test_r10_h4_a11y.py',
    'smass_operations/tests/test_r10_h6_security.py',
    'smass_operations/tests/test_r10_h7_e2e.py',
    'smass_operations/tests/test_h3_repro.py',
]

REQUIRED_MIGRATIONS = [
    'r21_account/migrations/0002_active_role_unique.py',
    'smass_workflow/migrations/0003_open_task_unique.py',
]

REQUIRED_SCRIPTS = [
    'scripts/r10_release_hardening_gate.py',
    'scripts/r10_uniqueness_precheck.py',
    'scripts/r10_upgrade_clone_drill.py',
    'scripts/r10_browser_probe.py',
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
    """关键产物必须真实存在。"""
    warnings = []

    for name in REQUIRED_DOCS:
        path = BASE / 'docs' / name
        if not path.exists():
            warnings.append('缺少文档: docs/{}'.format(name))
        elif path.stat().st_size < 500:
            warnings.append('文档过短（可能为占位）: docs/{}'.format(name))

    for rel in REQUIRED_TEST_FILES:
        if not (BASE / rel).exists():
            warnings.append('缺少测试文件: {}'.format(rel))

    for rel in REQUIRED_MIGRATIONS:
        if not (BASE / rel).exists():
            warnings.append('缺少迁移文件: {}'.format(rel))

    for rel in REQUIRED_SCRIPTS:
        if not (BASE / rel).exists():
            warnings.append('缺少脚本: {}'.format(rel))

    shots = BASE / 'docs' / 'screenshots' / 'r10_uiux'
    if not shots.exists():
        warnings.append('缺少截图目录: docs/screenshots/r10_uiux')
    else:
        pngs = list(shots.glob('*.png'))
        if len(pngs) < 10:
            warnings.append('截图数量偏少: {} 张（期望 >= 10）'.format(len(pngs)))

    return warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--artifacts', action='store_true')
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
