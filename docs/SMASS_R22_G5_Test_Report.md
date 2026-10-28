# SMASS R2.2 G5 测试报告（Test Report）

- 执行时间：2026-10-27
- 环境：conda `smass`（`C:\Users\MSIPC\.conda\envs\smass\python.exe`，Python 3.12.16 / Django 5.2.17）
- 隔离：G5 自动化测试跑在 `test_smass_r22_proto`；演练跑在 `smass_r22_g5_stage`；正式库 `smass` 只读

## 1. 结果总览

| 套件 | 命令 | 用例 | 结果 | 耗时 |
|---|---|---|---|---|
| G5 新增 | `test r22_account.tests.test_g5_backfill --settings=smass.settings_r22` | **18** | **PASS** | 2.798 s |
| R2.2 全量 | `test r22_account --settings=smass.settings_r22` | **57** | **PASS** | 12.934 s |
| R2.1 | `test r21_account --settings=smass.settings_r21` | 72 | PASS | 70.933 s |
| 原有应用 | `test app01` | 114 | PASS | 88.944 s |
| 原有 E2E | `test tests_e2e` | 16 | PASS | 48.578 s |
| **合计** | — | **259** | **全绿** | — |

| 门禁 | 结果 |
|---|---|
| `manage.py check`（正式） | 0 issues |
| `manage.py check --settings=smass.settings_r22` | 0 issues |
| `makemigrations --check --dry-run` | No changes |

## 2. G5 用例构成（18）

| 类 | 用例数 | 覆盖 |
|---|---|---|
| `TargetGuardTests` | 3 | 正式库被拒、未知库被拒、校验命令同样受限 |
| `BackfillFlowTests` | 6 | dry-run 不写、实跑产出、幂等、`--since`、哈希原样、强制改密标记 |
| `FaultInjectionTests` | 1 | Profile 创建失败只回滚该行 |
| `RollbackScopeTests` | 3 | 只删回填账号、旧表不动、二次回填恢复 |
| `ConsistencyDetectionTests` | 5 | pristine、缺映射、错角色、状态矛盾、strict 差异 |

## 3. 演练编排（脚本级证据）

`scripts/r22_g5_drill.py`（stage 库，`overall=PASS`）：

| 检查 | 结果 |
|---|---|
| 3 类差异注入全部检出 | PASS |
| 注入后恢复 pristine | PASS（计数完全一致） |
| 回滚范围（预存账号存活） | PASS |
| 回滚只删回填产物 | PASS |
| 二次回填恢复 | PASS |
| strict 差异由预存账号解释 | PASS |

## 4. 本轮真实失败与修复（4 轮）

| # | 失败 | 根因 | 修复 |
|---|---|---|---|
| 1 | root 无法连接（`caching_sha2_password` 需要 cryptography） | `FLUSH PRIVILEGES` 清空认证缓存后触发 full auth，PyMySQL 缺依赖 | 安装 `cryptography 50.0.2`（同时修复既有脚本的隐性风险） |
| 2 | 只读用户认证失败 | MySQL 8 默认 `caching_sha2_password` | 显式 `IDENTIFIED WITH mysql_native_password` |
| 3 | 二次回填后 `after_refill_ok=false` | 预存账号使 `--strict-count` 必然差 1（断言用错） | 非 strict 校验 + 单独解释 strict 差异 |
| 4 | `LINK_ACCOUNT_MISMATCH` 误报 | 校验器把"账号多于映射"当异常 | 改为仅 `links > accounts` 报错，新增精确的 `UNLINKED_ACCOUNT` |
| 5 | G5 测试断言 `created=3` 找不到 | 命令用 `print()` 而未走 `self.stdout` | `Stats.report(stream=self.stdout.write)` |
| 6 | 测试夹具字段不匹配 | `app01.Admin` 只有 id/name/password；`Teacher.political` NOT NULL | 按真实模型修正夹具 |

## 5. 未运行

| 项 | 状态 | 原因 |
|---|---|---|
| 并发回填 | NOT RUN | 无并发基准，不臆造 |
| 大数据量（万级）回填 | NOT RUN | 仅 6 行样本 |
| 浏览器级回填界面 | NOT RUN | 无 UI（G7 范围） |
| 审计链回滚一致性 | NOT RUN | 见 Rollback Report §5 |
