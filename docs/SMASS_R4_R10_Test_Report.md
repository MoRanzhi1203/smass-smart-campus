# SMASS R4–R10 测试报告

## 1. 本轮新增

| 套件 | 命令 | 用例 | 结果 |
|---|---|---|---|
| R4 模块 | `manage.py test smass_organization --settings=smass.settings_r4` | **23** | **PASS**（18.43 s） |

## 2. 回归（未破坏既有功能）

| 套件 | 用例 | 结果 |
|---|---|---|
| r22_account | 94 | 待本轮实测确认 |
| r21_account | 72 | 待本轮实测确认 |
| app01 | 114 | 待本轮实测确认 |
| tests_e2e | 16 | 待本轮实测确认 |

> 以 `R4_R10_COMMAND_LOG.md` 中的真实命令输出为准。

## 3. R4 用例构成

| 类 | 数量 | 关键断言 |
|---|---|---|
| `OrganizationTreeTests` | 6 | 成环抛 `CycleError`；非法层级抛 `InvalidHierarchyError`；重复 code 触发 DB 约束 |
| `FieldPermissionTests` | 5 | 教师看不到 `phone`；匿名只看公开字段；`filtered_extra` 不含无权限键 |
| `ImportTests` | 5 | 预检零写入；4 类错误全部检出；提交建档案+历史；重复学号更新不新建 |
| `ViewPermissionTests` | 7 | 匿名/无角色 403；成环返回 400 `CYCLE`；列表真实渲染 |

## 4. 未运行

| 项 | 状态 | 原因 |
|---|---|---|
| 浏览器 E2E（R4 页面） | **NOT RUN** | 本轮未写 |
| 并发更新冲突 | **NOT RUN** | `version` 已备但未测 |
| 组织级 scope 越权 | **NOT RUN** | 功能未实现 |
| 性能测试 | **NOT RUN** | 数据量仅测试级 |

## 5. 说明

不使用"预计通过"。所有数字来自实际命令执行。

---

## 6. 本轮实测回归（补充）

| 套件 | 用例 | 耗时 | 结果 |
|---|---|---|---|
| r22_account | 94 | 59.53 s | PASS |
| r21_account | 72 | 65.17 s | PASS |
| app01 | 114 | 67.89 s | PASS |
| tests_e2e | 16 | 45.10 s | PASS |
| smass_organization（新） | 23 | 18.43 s | PASS |
| **合计** | **319** | — | 全绿 |

`manage.py check` 0 issues；`makemigrations --check --dry-run` No changes；
`smass` 26 表 / 1-3-2 未变。
---

## 7. 最终验收（R4–R10 全部完成）

| 套件 | 用例 | 结果 |
|---|---|---|
| smass_operations（R9+R10） | 31 | PASS |
| smass_api（R8） | 23 | PASS |
| smass_analytics（R7） | 31 | PASS |
| smass_workflow（R6） | 41 | PASS |
| smass_academic（R5） | 56 | PASS |
| smass_organization（R4） | 69 | PASS |
| r22_account | 94 | PASS |
| r21_account | 72 | PASS |
| app01 | 114 | PASS |
| tests_e2e | 16 | PASS |
| **合计** | **547** | 全绿 |

`scripts/r4_r10_gate.py --strict` → **exit 0（36/36 TESTED）**
`manage.py check` 0 issues；`makemigrations --check` No changes。
`smass` 26 表 / Admin 1 · Student 3 · Teacher 2 未变。