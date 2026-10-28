# SMASS R2.2 基线报告（G0 Baseline Report）

- 执行时间：2026-10-27
- 分支：`feat/smass-r22-account-cutover`（基点 `b527cba`）
- 说明：全部数据来自本轮实机执行，未沿用 R2.1 报告数字。

## 1. 计划假设 vs 实机

| 项 | 计划/报告假设 | 实机实测 | 处理 |
|---|---|---|---|
| R2.1 分支 / HEAD | `feat/smass-r21-account-rbac` @ `b527cba` | 一致 | 已从其新建 R2.2 分支 |
| 工作区 | 干净 | `dirty=0` | 未覆盖任何未提交改动 |
| 解释器 | `E:\anaconda3\envs\smass\python.exe` | **不存在**；实际 `C:\Users\MSIPC\.conda\envs\smass\python.exe` | 全程用实测路径，未用 base |
| Python / Django | 3.12.16 / 5.2.17 | 一致 | — |
| Pillow / PyMySQL | — | 13.0.0 / 1.4.6 | — |
| `main` 基线 | `84e290b` | 一致（未动） | — |

## 2. Git

| 项 | 值 |
|---|---|
| 新分支 | `feat/smass-r22-account-cutover` |
| 基点 | `b527cba` |
| 既有分支 | `main`@`84e290b`、`feat/smass-r15-r20-hardening`@`13fd95f`、`feat/smass-r21-account-rbac`@`b527cba` |
| 起始脏状态 | 0（无未提交改动） |

## 3. 数据库清单（冻结基线）

| 库 | 用途 | 本轮处理 |
|---|---|---|
| `smass` | 开发库 | **只读**；26 表，Admin 1 / Student 3 / Teacher 2 未变 |
| `smass_proto_account` | R2.0 路径 A 原型 | 保留不动 |
| `smass_proto_user_model` | R2.0 路径 B 原型 | 保留不动 |
| `smass_r21_proto` | R2.1 原型（6 账号） | 保留不动 |
| `smass_r22_b_proto` | **本轮新建**：B 路径全新库实验 | 迁移成功，保留为证据 |
| `smass_r22_b_switch` | **本轮新建**：B 路径"中途切换"实验 | 处于半切换状态（见兼容性审计），保留为证据 |
| 实例库总数 | 34 | 20+ 无关业务库未触碰 |

> `smass_r22_*` 为本轮实验库，可后续清理；**未删除任何旧表或既有原型库**。

## 4. 测试基线冻结（本轮实跑）

| 套件 | 命令 | 结果 |
|---|---|---|
| R2.1 应用 | `manage.py test r21_account --settings=smass.settings_r21` | **60/60 PASS** |
| 原有应用 | `manage.py test app01` | **114/114 PASS** |
| 原有 E2E | `manage.py test tests_e2e` | **16/16 PASS** |
| 依赖漏洞 | `pip-audit -r requirements.txt` | **PASS**（0 漏洞） |
| Django 检查 | `manage.py check` | **PASS**（0 issues） |

> R2.2 新增的兼容性审计用例为 12 例，见兼容性审计报告；合计 R2.2 阶段验证 12 例。

## 5. G0 结论

**PASS** —— 环境、分支、数据库清单与测试基线均已实机确认；未修改 `smass`，未删除任何既有库。
