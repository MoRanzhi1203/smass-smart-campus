# 10 测试与回归

> 目标：不通过跳过测试、弱化约束或降低权限来“变绿”。

---

## 1. 测试矩阵（计划与本轮已执行）

| 套件 | 范围 | 状态 |
|---|---|---|
| `smass_workspace`（156 例） | 产品层三端 + 宿舍 UI + 管理端宿舍 | 待本轮/下轮复跑（默认配置改为 campus 后需确认） |
| `smass_simulation` + `smass_dormitory`（26 例） | 生成器/教学/宿舍服务/校验/清理 | 待复跑 |
| V2.2 验收脚本 | 6 角色浏览器（明/暗 × 桌面/移动）+ 写操作 | **已执行 PASS** |

## 2. 浏览器与写操作验收（实测）

脚本：`scripts/v22_acceptance.py`（`--base http://127.0.0.1:8050`）

| 项 | 结果 |
|---|---|
| 浏览器检查 | **24**（6 角色 × 2 主题 × 2 视口），失败 0 |
| 截图 | `.local/evidence/v22/acceptance/*.png`（24 张） |
| 学生页 | 200 |
| 学生登录 | 302 → `/student/` |
| 报修创建 | ✅（`DormRepair` 落库） |
| 宿管推进报修 | ✅（`submitted → assigned`） |
| 越权审批 | ✅ **403**（非授权楼栋，`cross_scope_forbidden`） |
| 教师创建考勤场 | ✅（`AttendanceSession` 落库） |
| 清理 | 所有测试写入在 `finally` 中删除，演示数据最终状态不变 |

## 3. 回归注意点

1. `manage.py` 默认改为 `settings_campus` → 测试默认库变为 `test_smass_campus`；
   需确认两个套件在 campus 配置下仍全绿（含新表结构）。
2. 生成器改动：学年 code `SIM-2025 → 2025`、账单号 `SIM-BILL- → BILL-`、
   缴费号 `SIM-PAY- → PAY-`、排课算法 `simulation-greedy → greedy`；
   `cleanup.py`/`verify.py` 的过滤字面量已同步。
3. 页面层：宿舍/账单/排课页面已去除 `SIM-`/`simulation` 字样（实测 0 残留）。

## 4. 待补

- 产品层与 V2.1 套件在 campus 下的完整复跑结果；
- 性能采样（10 页面）在 campus 的实测数字；
- 全量回归与 V2.1 文档交叉引用。
