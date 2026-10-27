# SMASS R1.5 基线报告（Baseline Report）

- 执行时间：2026-10-27
- 分支：`feat/smass-r15-r20-hardening`
- 说明：本报告所有数据来自**本轮实机执行**，未引用上一轮交付报告中的数字。

## 1. 计划假设 vs 实机实测

| 项 | 计划假设 | 实机实测 | 处理 |
|---|---|---|---|
| 解释器 | `E:\anaconda3\envs\smass\python.exe` | **不存在**；实际为 `C:\Users\MSIPC\.conda\envs\smass\python.exe` | 全流程使用实测路径（绝对路径或 `conda run -n smass`），不使用 base |
| Python | 3.12.16 | 3.12.16 | 一致 |
| Django | 5.2.13 | 5.2.13 | 一致 |
| 起始分支 / HEAD | 参考 `84e290b` | `main` @ `84e290b` | 已新建独立分支 |
| Shell | 未说明 | Windows PowerShell 5.1（**无 pwsh 7**） | 脚本用 `powershell -File`，并加 UTF-8 BOM 保证中文解析 |
| 测试文件名 | 报告曾写 `text_auth.py` | 实际 `test_auth.py` | 以 `manage.py test` 发现结果为准 |
| MySQL 工具 | 未说明 | `mysqldump`/`mysql` 均在 `D:\mysql-8.0.18-winx64\bin`（8.0.18） | 与服务器版本一致，可用 |

## 2. Git 状态

| 项 | 值 |
|---|---|
| 起始 HEAD | `84e290b`（fix(r1-review)…） |
| 起始脏状态 | 仅 1 个未跟踪文件（用户提供的计划 md），**无代码脏改动** |
| 新分支 | `feat/smass-r15-r20-hardening` |
| 分支基点提交 | `d4caa88`（纳入计划文件） |
| 本轮提交 | `df4d537`（R1.5-A）、`3780591`（R1.5-B）、`94a1a96`（R1.5-C/D/R2.0） |

## 3. 数据库基线（只读核验）

| 项 | 实测值 |
|---|---|
| 实例 | MySQL 8.0.18 @ localhost:3306 |
| 目标库 | `smass`，**26 张表** |
| 字符集 | 库/表/53 个字符列全部 `utf8`（`utf8_general_ci`）；52 个索引 |
| 数据量 | Admin 1 / Teacher 2 / Student 3 / College 2 / Major 3 / Classes 2 / Grade 3 / Position 4 / TeacherPosition 2 / Department 2 / LeagueCadres 1 / ClassCommittee 1 = **158 行** |
| 外键 | 24 |
| 迁移 | `app01` 0001–0004 全部 `[X]`；`django_migrations` 22 条 |
| 数据性质 | **开发种子数据**（与上一轮 `seed_dev` 产出结构一一对应，无用户录入痕迹） |
| 同实例其他库 | 共 29 个库，含 `school`、`ruoyi`、`hospital_mgmt` 等 20+ 无关业务库 → 明确列为禁触区 |
| 连接账号 | `root`@`localhost`，具备 ALL PRIVILEGES + GRANT OPTION（可备份/恢复，但不因此扩大操作范围） |

## 4. 基线门禁（本次实跑）

先静态审查 `scripts/check.ps1`：仅含 `check`、`makemigrations --check --dry-run`、`test app01`、
`check --deploy`，**无 Remove-Item / drop / flush / migrate 等破坏性调用**，可安全执行。

```
=== django check ===        System check identified no issues (0 silenced)
=== migration check ===     No changes detected
=== unit tests ===          Ran 87 tests in 52.591s   OK
=== deploy audit ===        6 warnings（开发环境预期）
ALL GATES PASSED            gate_exit=0
```

| 门禁 | 结果 |
|---|---|
| django check | PASS（0 issues） |
| 迁移一致性 | PASS（No changes detected） |
| 单元测试 | **PASS 87/87**（52.591s，`test_smass` 自动建/销毁） |
| deploy 审计 | WARN ×6（W004/008/009/012/016/018，开发环境预期） |

## 5. 测试文件实名

```
app01/tests/__init__.py
app01/tests/helpers.py
app01/tests/test_auth.py
app01/tests/test_authorization.py
app01/tests/test_compat_tools.py
app01/tests/test_crud_admin.py
app01/tests/test_high_risk.py      ← 本轮新增
app01/tests/test_imports.py
```

以运行发现为准：基线 87 条 → 本轮收尾 109 条。

## 6. R0 结论

| 门禁项 | 结论 |
|---|---|
| 解释器明确 | PASS（实机路径，非 base） |
| 代码版本可追踪 | PASS（独立分支 + 4 个提交） |
| 数据库隔离已证实 | PASS（`smass` 开发种子库；20+ 无关库列名在案） |
| 原有测试实测记录 | PASS（87/87，52.591s） |

**R0 门禁：PASS**
