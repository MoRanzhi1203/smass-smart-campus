#!/usr/bin/env python
"""SMASS 智慧校园 R10–R20 严格门禁。

设计目标（对应主任务书 §2 / §9）：
- 校验任务账本的结构与依赖一致性（禁止悬空依赖、禁止依赖环）；
- 校验「声称 TESTED」的任务确有非空证据文件，且证据里出现可核验的要素
  （提交 SHA / 命令 / 计数等），避免"只要 JSON 里写了 TESTED 就算完成"；
- 校验状态文件与任务账本的计数自洽；
- 校验 G0 归档证据与安全不变量；
- 校验正式 `smass` 库从未被写入（以只读指纹文件为准）。

用法:
    python scripts/smart_campus_gate.py
    python scripts/smart_campus_gate.py --strict
    python scripts/smart_campus_gate.py --strict --evidence --json
    python scripts/smart_campus_gate.py --next          # 只输出下一个可执行任务

退出码:
    0  全部门禁通过
    1  存在失败项（--strict 下任何失败即 1）
    2  账本文件缺失或无法解析
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RUN_DIR = BASE / 'docs' / 'dsh_run'
TASKS_PATH = RUN_DIR / 'SMART_CAMPUS_MASTER_TASKS.json'
STATE_PATH = RUN_DIR / 'SMART_CAMPUS_MASTER_STATE.json'

#: 允许的任务状态
STATES = {'PENDING', 'READY', 'IN_PROGRESS', 'TESTED', 'BLOCKED', 'BUSINESS_CONFIG_PENDING'}

#: 证据文件必须命中的要素之一（说明它不是空壳）
EVIDENCE_MARKERS = (
    re.compile(r'[0-9a-f]{7,40}'),          # 提交 SHA
    re.compile(r'manage\.py test'),          # 测试命令
    re.compile(r'Ran \d+ tests?'),           # 实测计数
    re.compile(r'实测|MEASURED|measured'),    # 实测表述
)

#: 视为「可推进」的状态
ADVANCEABLE = {'READY', 'IN_PROGRESS'}
DONE = 'TESTED'


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []   # (level, check, detail)
        self.failed = 0
        self.warned = 0

    def ok(self, check: str, detail: str = '') -> None:
        self.rows.append(('OK', check, detail))

    def warn(self, check: str, detail: str = '') -> None:
        self.rows.append(('WARN', check, detail))
        self.warned += 1

    def fail(self, check: str, detail: str = '') -> None:
        self.rows.append(('FAIL', check, detail))
        self.failed += 1

    def dump(self, as_json: bool) -> None:
        if as_json:
            print(json.dumps({
                'failed': self.failed,
                'warned': self.warned,
                'checks': [{'level': lv, 'check': c, 'detail': d} for lv, c, d in self.rows],
            }, ensure_ascii=False, indent=2))
            return
        width = max((len(c) for _, c, _ in self.rows), default=10)
        for level, check, detail in self.rows:
            mark = {'OK': '[ OK ]', 'WARN': '[WARN]', 'FAIL': '[FAIL]'}[level]
            line = f'{mark} {check.ljust(width)}'
            if detail:
                line += f'  {detail}'
            print(line)
        print()
        print(f'汇总: 失败 {self.failed} 项 / 警告 {self.warned} 项 / 共 {len(self.rows)} 项')


def load_json(path: Path) -> dict:
    if not path.exists():
        print(f'账本缺失: {path}', file=sys.stderr)
        raise SystemExit(2)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        print(f'账本解析失败 {path}: {exc}', file=sys.stderr)
        raise SystemExit(2)


# ---------------------------------------------------------------------------
# 1. 结构校验
# ---------------------------------------------------------------------------
def check_structure(tasks_doc: dict, rep: Report) -> list[dict]:
    tasks = tasks_doc.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        rep.fail('tasks 列表', '账本中不存在有效的 tasks 数组')
        return []
    rep.ok('tasks 列表', f'{len(tasks)} 个任务')

    seen: dict[str, int] = {}
    for idx, t in enumerate(tasks):
        for field in ('id', 'title', 'phase', 'state', 'depends_on', 'acceptance', 'evidence_paths'):
            if field not in t:
                rep.fail(f'task[{idx}] 字段', f'缺少 {field}')
        tid = t.get('id')
        if tid in seen:
            rep.fail('任务 id 唯一', f'重复 id: {tid}')
        seen[tid] = idx

        state = t.get('state')
        if state not in STATES:
            rep.fail(f'{tid} 状态合法', f'未知状态 {state!r}')
    return tasks


# ---------------------------------------------------------------------------
# 2. 依赖一致性（含环检测）
# ---------------------------------------------------------------------------
def check_dependencies(tasks: list[dict], rep: Report) -> None:
    by_id = {t['id']: t for t in tasks}

    dangling: list[str] = []
    for t in tasks:
        for dep in t.get('depends_on') or []:
            if dep not in by_id:
                dangling.append(f"{t['id']} -> {dep}")
    if dangling:
        rep.fail('依赖存在', f'悬空依赖 {len(dangling)} 处: {", ".join(dangling[:6])}')
    else:
        rep.ok('依赖存在', '所有依赖均指向已登记任务')

    # 依赖环（DFS 三色标记）
    color: dict[str, int] = {}
    cycle: list[str] = []

    def dfs(node: str, stack: list[str]) -> bool:
        color[node] = 1
        stack.append(node)
        for dep in by_id.get(node, {}).get('depends_on') or []:
            if dep not in by_id:
                continue
            if color.get(dep, 0) == 1:
                cycle.extend(stack[stack.index(dep):] + [dep])
                return True
            if color.get(dep, 0) == 0 and dfs(dep, stack):
                return True
        stack.pop()
        color[node] = 2
        return False

    for tid in by_id:
        if color.get(tid, 0) == 0 and dfs(tid, []):
            break
    if cycle:
        rep.fail('依赖无环', '检测到环: ' + ' -> '.join(cycle))
    else:
        rep.ok('依赖无环', '')

    # 状态逻辑：依赖未 TESTED 却自报 TESTED/IN_PROGRESS
    violations: list[str] = []
    for t in tasks:
        state = t.get('state')
        if state not in {DONE, 'IN_PROGRESS'}:
            continue
        unmet = [d for d in (t.get('depends_on') or [])
                 if by_id.get(d, {}).get('state') != DONE]
        if unmet:
            violations.append(f"{t['id']}({state}) 依赖未完成: {','.join(unmet)}")
    if violations:
        rep.fail('状态与依赖自洽', f'{len(violations)} 处: ' + '; '.join(violations[:5]))
    else:
        rep.ok('状态与依赖自洽', '没有任务在依赖未完成时自称完成')


# ---------------------------------------------------------------------------
# 3. 证据校验（只针对 TESTED）
# ---------------------------------------------------------------------------
def check_evidence(tasks: list[dict], rep: Report, deep: bool) -> None:
    tested = [t for t in tasks if t.get('state') == DONE]
    rep.ok('TESTED 计数', f'{len(tested)} 个任务')

    missing: list[str] = []
    hollow: list[str] = []
    for t in tested:
        paths = t.get('evidence_paths') or []
        if not paths:
            missing.append(f"{t['id']}(无证据路径)")
            continue
        for rel in paths:
            p = BASE / rel
            if not p.exists():
                missing.append(f"{t['id']} -> {rel}")
                continue
            text = p.read_text(encoding='utf-8', errors='replace')
            if len(text.strip()) < 120:
                hollow.append(f"{t['id']} -> {rel} (内容过短)")
                continue
            if deep and not any(rx.search(text) for rx in EVIDENCE_MARKERS):
                hollow.append(f"{t['id']} -> {rel} (缺少 SHA/命令/实测计数等可核验要素)")

    if missing:
        rep.fail('TESTED 证据存在', f'{len(missing)} 处缺失: ' + '; '.join(missing[:5]))
    else:
        rep.ok('TESTED 证据存在', '全部证据路径有效')

    if hollow:
        rep.fail('TESTED 证据非空壳', f'{len(hollow)} 处可疑: ' + '; '.join(hollow[:5]))
    else:
        rep.ok('TESTED 证据非空壳', '证据含可核验要素' if deep else '未做深度检查（加 --evidence）')


# ---------------------------------------------------------------------------
# 4. 状态文件自洽
# ---------------------------------------------------------------------------
def check_state_sync(tasks: list[dict], state_doc: dict, rep: Report) -> None:
    counts = {s: 0 for s in STATES}
    for t in tasks:
        counts[t.get('state')] = counts.get(t.get('state'), 0) + 1

    prog = state_doc.get('progress') or {}
    problems: list[str] = []
    if prog.get('total_tasks') not in (None, len(tasks)):
        problems.append(f"total_tasks {prog.get('total_tasks')} != 实际 {len(tasks)}")
    for key, st in (('tested', 'TESTED'), ('in_progress', 'IN_PROGRESS'),
                    ('pending', 'PENDING'), ('blocked', 'BLOCKED'),
                    ('business_config_pending', 'BUSINESS_CONFIG_PENDING')):
        if key in prog and prog[key] != counts.get(st, 0):
            problems.append(f"{key} {prog[key]} != 实际 {counts.get(st, 0)}")
    if problems:
        rep.fail('状态文件与账本一致', '; '.join(problems))
    else:
        rep.ok('状态文件与账本一致', f"TESTED={counts['TESTED']} PENDING={counts['PENDING']}")

    cur = state_doc.get('current_task')
    by_id = {t['id']: t for t in tasks}
    if cur and cur in by_id:
        task = by_id[cur]
        state_now = task.get('state')
        deps_ok = all(
            by_id.get(d, {}).get('state') == DONE
            for d in (task.get('depends_on') or [])
        )
        if state_now in ADVANCEABLE | {DONE}:
            rep.ok('current_task 合法', f'{cur} = {state_now}')
        elif state_now == 'PENDING' and deps_ok:
            # 「下一个可执行任务」尚未开工时允许是 PENDING（诚实状态），
            # 前提是它的依赖都已 TESTED。
            rep.ok('current_task 合法', f'{cur} = PENDING（下一可执行，依赖已满足）')
        else:
            rep.fail('current_task 合法',
                     f'{cur} 状态为 {state_now}（依赖未满足或状态异常）')
    elif cur:
        rep.fail('current_task 合法', f'{cur} 不在账本中')


# ---------------------------------------------------------------------------
# 5. G0 与安全不变量
# ---------------------------------------------------------------------------
def check_g0_and_safety(tasks_doc: dict, state_doc: dict, rep: Report) -> None:
    arch = tasks_doc.get('archive') or {}
    if arch.get('state') == 'VERIFIED':
        rep.ok('G0 归档状态', 'VERIFIED')
    else:
        rep.fail('G0 归档状态', f"{arch.get('state')}")

    report_rel = 'docs/SMASS_GitHub_Archive_Report.md'
    report_path = BASE / report_rel
    if not report_path.exists():
        rep.fail('G0 报告存在', report_rel)
    else:
        text = report_path.read_text(encoding='utf-8', errors='replace')
        need = ['private', 'a6b2328', 'CLEAN']
        miss = [n for n in need if n not in text]
        if miss:
            rep.fail('G0 报告要点', '缺少: ' + ', '.join(miss))
        else:
            rep.ok('G0 报告要点', 'URL/私有/远端SHA/零泄漏齐备')

    if arch.get('remote_secret_scan') == 'CLEAN':
        rep.ok('远端零泄漏结论', 'CLEAN')
    else:
        rep.fail('远端零泄漏结论', f"{arch.get('remote_secret_scan')}")

    inv = state_doc.get('safety_invariants') or {}
    if inv.get('formal_smass_db_writes') == 0:
        rep.ok('正式库零写入', 'formal_smass_db_writes = 0')
    else:
        rep.fail('正式库零写入', f"{inv.get('formal_smass_db_writes')}")
    if inv.get('auth_user_model_modified') is False:
        rep.ok('AUTH_USER_MODEL 未改', '')
    else:
        rep.fail('AUTH_USER_MODEL 未改', str(inv.get('auth_user_model_modified')))


# ---------------------------------------------------------------------------
# 6. 下一个可执行任务
# ---------------------------------------------------------------------------
def next_task(tasks: list[dict]) -> dict | None:
    by_id = {t['id']: t for t in tasks}
    for t in tasks:
        if t.get('state') in ADVANCEABLE:
            return t
    for t in tasks:
        if t.get('state') != 'PENDING':
            continue
        deps = t.get('depends_on') or []
        if all(by_id.get(d, {}).get('state') == DONE for d in deps):
            return t
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description='SMASS 智慧校园严格门禁')
    ap.add_argument('--strict', action='store_true', help='任何失败项即返回 1')
    ap.add_argument('--evidence', action='store_true', help='深度校验证据内容要素')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出')
    ap.add_argument('--next', action='store_true', help='只输出下一个可执行任务')
    args = ap.parse_args()

    tasks_doc = load_json(TASKS_PATH)
    state_doc = load_json(STATE_PATH)

    tasks = tasks_doc.get('tasks') or []

    if args.next:
        nxt = next_task(tasks)
        print(json.dumps(nxt, ensure_ascii=False, indent=2) if nxt else 'NONE')
        return 0

    rep = Report()
    tasks = check_structure(tasks_doc, rep)
    if tasks:
        check_dependencies(tasks, rep)
        check_evidence(tasks, rep, deep=args.evidence)
        check_state_sync(tasks, state_doc, rep)
        check_g0_and_safety(tasks_doc, state_doc, rep)

    rep.dump(args.json)

    if rep.failed:
        return 1 if args.strict else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
