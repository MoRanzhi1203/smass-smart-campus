#!/usr/bin/env python
"""账本状态同步工具。

用一个可重复执行的脚本更新 TASKS/STATE，避免手改 JSON 时出现
"改了 tasks 忘了 state" 的计数漂移（门禁已经抓到过两次这类不一致）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(r"E:\PythonWeb\smass")
RUN_DIR = _resolve_run_dir()
TASKS = RUN_DIR / "SMART_CAMPUS_MASTER_TASKS.json"
STATE = RUN_DIR / "SMART_CAMPUS_MASTER_STATE.json"


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recompute(state: dict, tasks: list[dict]) -> dict:
    counts = {"TESTED": 0, "IN_PROGRESS": 0, "PENDING": 0,
              "BLOCKED": 0, "BUSINESS_CONFIG_PENDING": 0, "READY": 0}
    for t in tasks:
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    state["progress"] = {
        "total_tasks": len(tasks),
        "tested": counts["TESTED"],
        "in_progress": counts["IN_PROGRESS"],
        "pending": counts["PENDING"],
        "blocked": counts["BLOCKED"],
        "business_config_pending": counts["BUSINESS_CONFIG_PENDING"],
    }
    return state


def main() -> int:
    tasks_doc = load(TASKS)
    state = load(STATE)
    tasks = tasks_doc["tasks"]

    # 由调用方在命令行给出 id=state 形式的更新
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"skip malformed arg {arg!r}")
            continue
        tid, new_state = arg.split("=", 1)
        hit = [t for t in tasks if t["id"] == tid]
        if not hit:
            print(f"unknown task id {tid!r}")
            return 2
        hit[0]["state"] = new_state
        print(f"{tid} -> {new_state}")

    # 当前任务 = 第一个 IN_PROGRESS；否则取第一个依赖已满足的 PENDING
    by_id = {t["id"]: t for t in tasks}
    current = next((t for t in tasks if t["state"] == "IN_PROGRESS"), None)
    if current is None:
        current = next(
            (t for t in tasks
             if t["state"] == "PENDING"
             and all(by_id.get(d, {}).get("state") == "TESTED" for d in t.get("depends_on", []))),
            None,
        )
    if current:
        state["current_task"] = current["id"]
        state["next_task"] = current["id"]
        state["current_phase"] = current.get("phase", state.get("current_phase"))

    state = recompute(state, tasks)
    dump(TASKS, tasks_doc)
    dump(STATE, state)
    print("progress =", json.dumps(state["progress"], ensure_ascii=False))
    print("current =", state["current_task"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
