# SMASS R10 Hardening Execution Report（H8）

- 基线：`488f6c5`　分支：`feat/smass-r4-r10-integrated-platform`
- 设置：`smass.settings_r10`（READ COMMITTED）
- 测量方式：`scripts/r10_full_regression.py`（**实际跑一遍并统计，不硬编码**）

## 1. 全量回归（实测）

| 套件 | settings | 用例 | 耗时 | 结果 |
|---|---|---|---|---|
| `smass_operations` | `settings_r10` | **295** | 278.2s | PASS |
| `smass_analytics` | `settings_r7` | 31 | 30.5s | PASS |
| `smass_organization` | `settings_r4` | 69 | 60.8s | PASS |
| `smass_academic` | `settings_r5` | 56 | 50.9s | PASS |
| `smass_workflow` | `settings_r6` | 41 | 24.0s | PASS |
| `smass_api` | `settings_r8` | 23 | 14.6s | PASS |
| `r22_account` | `settings_r22` | 94 | 44.6s | PASS |
| `r21_account` | `settings_r21` | 72 | 59.1s | PASS |
| `app01` | formal | 114 | 59.8s | PASS |
| `tests_e2e` | formal | 16 | 39.8s | PASS |
| **合计** | | **811** | ≈11.4 分钟 | **全绿** |

**对比**：R10 UI/UX 阶段基线 733 → 现 811，**新增 78 例**
（H1 18 + H2 10 + H3 repro 2 + H4 15 + H6 27 + H7 6）。

## 2. 质量门禁

| 检查 | 命令 | 结果 |
|---|---|---|
| Django check（正式） | `manage.py check` | **0 issues** |
| Django check（r10） | `--settings=smass.settings_r10` | **0 issues** |
| 迁移一致性（正式） | `makemigrations --check --dry-run` | **No changes** |
| 迁移一致性（r10） | 同上 + `settings_r10` | **No changes** |
| 迁移一致性（r21） | 同上 + `settings_r21` | **No changes** |
| 依赖审计 | `pip-audit -r requirements.txt` | **No known vulnerabilities found** |
| 秘密扫描 | `scripts/r9_secret_scan.py` | **PASS**（0 生产凭据；49 处测试夹具已识别） |
| 源库指纹 | `scripts/db_inspect.py` | **26 表** / Admin 1 · Student 3 · Teacher 2（未变） |

## 3. 迁移审计

新增迁移（均加法、可逆）：

| 迁移 | 作用 | 反向 |
|---|---|---|
| `r21_account/0002_active_role_unique` | `active_account_id` 生成列 + `uq_r21_active_role` | `DROP INDEX` + `DROP COLUMN` |
| `smass_workflow/0003_open_task_unique` | `open_instance_id` / `open_node_id` + `uq_r6_open_task` | 同上 |

两处均用 `SeparateDatabaseAndState`，state 侧移除 MySQL 建不出的条件约束，
database 侧执行真实 DDL。

实测可逆：索引行数 4 → 回滚 0 → 重应用 4。

## 4. 新增测试文件

| 文件 | 例数 | 覆盖 |
|---|---|---|
| `test_r10_h1_password.py` | 18 | 密码生命周期（强制改密、校验、CSRF、多会话） |
| `test_r10_h2_uniqueness.py` | 10 | DB 级唯一约束 + 4 线程并发 + 索引存在性 |
| `test_h3_repro.py` | 2 | WebKit 500 确定性复现（回归保护） |
| `test_r10_h4_a11y.py` | 15 | skip link / h1 / aria 关联 / 200% / 强制颜色 |
| `test_r10_h6_security.py` | 27 | 身份矩阵 / 跨面一致性 / 伪造请求 / 审计 |
| `test_r10_h7_e2e.py` | 6 | 跨模块旅程 / 强制改密 / 三视口 / 抽屉 |

## 5. 门禁脚本强化

`scripts/r10_release_hardening_gate.py` 现在有三层检查：

| 层 | 检查内容 |
|---|---|
| 结构 | ID 唯一、依赖存在、无环、状态合法 |
| 证据 | TESTED 必须有非空 evidence；依赖也必须 TESTED |
| 产物（`--artifacts`） | 10 份必需文档（且 ≥500 字节防占位）、6 个测试文件、2 个迁移文件、4 个脚本、截图目录 ≥10 张 |

退出码：`0` 通过 / `1` strict 未全绿或有警告 / `2` 结构性错误。

**关键**：门禁校验**证据与产物存在性**，不是只看状态字符串。

## 6. 测量工具

`scripts/r10_full_regression.py`：
- 逐套件在最合适的 settings 下运行
- 解析 `Ran N tests` 与 `FAILED (...)` 输出
- 输出每套件数量/耗时/结果 + 总计
- `--json` 输出结构化结果

**为什么不用硬编码 733**：代码在演进，测试数会变。
基线 733 是"当时的实测值"，本次实测 811 才是当前真值。

## 7. 未执行的检查

| 检查 | 状态 | 原因 |
|---|---|---|
| 生产数据量压测 | **NOT RUN** | 需要真实数据规模；本轮只有合成数据 |
| 多进程（非线程）并发 | **NOT RUN** | 需要多 worker 部署环境 |
| Docker/容器化构建 | **NOT RUN** | 项目未容器化 |
| 跨 MySQL 版本（5.7） | **NOT RUN** | 只在本机 8.0.18 验证 |
| 前端构建产物校验 | **N/A** | 无构建步骤（原生 JS + 本地 Bootstrap） |

## 8. 结论

**811 例全绿，10 个套件无失败**；check 0 issues；迁移一致（三套 settings）；
依赖无已知漏洞；秘密扫描 PASS；源库 26 表未变。

H8 的交付是"可重复的测量"，不是"一份静态数字"。
