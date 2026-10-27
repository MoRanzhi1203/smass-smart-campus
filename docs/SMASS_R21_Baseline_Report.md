# SMASS R2.1 基线报告（Baseline Report）

- 执行时间：2026-10-27
- 分支：`feat/smass-r21-account-rbac`（基点 `c97053b`，继承 `feat/smass-r15-r20-hardening@13fd95f`）
- 说明：全部数据来自本轮实机执行，未沿用旧报告数字。

## 1. 计划假设 vs 实机

| 项 | 计划假设 | 实机实测 | 处理 |
|---|---|---|---|
| 解释器 | `E:\anaconda3\envs\smass\python.exe` | **不存在**；实际 `C:\Users\MSIPC\.conda\envs\smass\python.exe` | 全程使用实测路径，未用 base |
| R1.5–R2.0 最终提交 | `13fd95f` | 一致 | — |
| `main` 基线 | `84e290b` | 一致 | — |
| 起始分支 | 未指定 | `feat/smass-r15-r20-hardening` @ `13fd95f` | 已新建 R2.1 分支 |
| 起始脏状态 | 未指定 | 仅 1 个未跟踪文件（本计划 md） | 已随基点提交，未覆盖用户改动 |

## 2. 环境版本（实测）

| 组件 | 版本 |
|---|---|
| Python | 3.12.16 |
| `sys.executable` | `C:\Users\MSIPC\.conda\envs\smass\python.exe` |
| Django | 5.2.17 |
| Pillow | 13.0.0 |
| PyMySQL | 1.4.6（conda 包） |
| MySQL | 8.0.18 |
| pip-audit | 2.10.1 |
| Playwright | 1.64.1（chromium headless shell 已装） |

## 3. Git

| 项 | 值 |
|---|---|
| 当前分支 | `feat/smass-r21-account-rbac` |
| 基点提交 | `c97053b`（纳入 R2.1 计划文件） |
| 上一轮交付 | `feat/smass-r15-r20-hardening` @ `13fd95f` |
| `main` | `84e290b`（未动） |
| 起始工作区 | 仅计划文件未跟踪，无代码脏改动 |

## 4. 数据库清单（只读核验）

| 库 | 用途 | 状态 |
|---|---|---|
| `smass` | 开发库 | **26 表 / Admin 1 · Student 3 · Teacher 2**，本轮全程未写入 |
| `smass_proto_account` | R2.0 路径 A 原型 | 存在，**按要求不删除** |
| `smass_proto_user_model` | R2.0 路径 B 原型 | 存在，**按要求不删除** |
| `smass_r21_proto` | **本轮新建**（隔离原型） | 已迁移，含 7 张 `r21_*` 表 |
| 实例总库数 | 32（原 31 + 本轮 r21） | 20+ 无关业务库未触碰 |

白名单约定：写入目标只允许 `smass_r21_*`；`smass` 只读；`smass_proto_*` 保留不动。

## 5. 原有门禁实跑（本轮）

| 门禁 | 命令 | 结果 |
|---|---|---|
| Django 检查 | `manage.py check` | **PASS**（0 issues） |
| 迁移一致性 | `makemigrations --check --dry-run` | **PASS**（No changes detected） |
| 应用测试 | `manage.py test app01` | **PASS 114/114**（64.698s） |
| 浏览器 E2E | `manage.py test tests_e2e` | **PASS 16/16**（35.525s） |
| 依赖漏洞 | `pip-audit -r requirements.txt` | **PASS**（No known vulnerabilities） |

上述数量与 R1.5 交付一致，说明基线未被破坏。

## 6. G0 结论

**PASS** —— 环境隔离、数据可恢复性（R1.5 已有备份+恢复演练证据）、可用分支、原测试基线均有真实记录。
