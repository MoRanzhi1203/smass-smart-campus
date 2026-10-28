# SMASS R2.2 G8 切换 Runbook（Cutover Runbook）

> **重要**：本 Runbook 是**准备材料**，不是执行记录。正式切换需单独授权。

## 1. 前置检查（全部为 PASS 才可申请）

| # | 检查 | 命令 / 方法 | 期望 |
|---|---|---|---|
| 1 | 源库只读 | 以只读账号执行 UPDATE | 被拒（1142） |
| 2 | 当前基线 | `git rev-parse HEAD` | 与评审记录一致 |
| 3 | 全量回归 | 4 个测试套件 | 267 PASS（当前） |
| 4 | 迁移一致 | `makemigrations --check --dry-run` | No changes |
| 5 | 依赖漏洞 | `pip-audit -r requirements.txt` | 0 |
| 6 | 回填一致性 | `verify_account_consistency --strict-count` | PASS |
| 7 | 备份可用 | 全量备份 + 恢复演练 | 恢复成功 |
| 8 | 回滚脚本演练 | 合成库全流程 | PASS |

## 2. 配置前后对照

| 项 | 切换前 | 切换后（建议） |
|---|---|---|
| `AUTHENTICATION_BACKENDS` | 默认 ModelBackend | `r21_account.backends.AccountBackend` |
| 身份中间件 | `app01.middleware.auth.AuthMiddleware` | `r22_account.middleware.IdentityMiddleware` + `RoutePolicyMiddleware` |
| `AUTH_USER_MODEL` | `auth.User` | **保持不变**（路径 A） |
| `R22_FLAGS.identity_mode` | 无（不加载） | `dual` → 观察期后 `account` |
| `app01` 视图身份来源 | `session['info']` | 逐步改为 `request.account`（需单独实施） |

## 3. 冻结窗口

| 项 | 建议 |
|---|---|
| 时长 | 30 分钟（回填 6 行规模 < 1 分钟；余量用于校验） |
| 时段 | 低峰期，避开选课/成绩提交 |
| 冻结范围 | 停止三端写操作（登录可保留） |
| 回滚决策点 | 切换后 10 分钟内若冲突率 > 1% 立即回滚 |

## 4. 执行步骤（草案）

1. 全量备份（`scripts/db_backup.ps1`），记录校验和；
2. 记录基线：表数、行数、`django_migrations` 最大 ID；
3. 应用只读回填（`backfill_accounts_r21`，先在克隆库演练过的同一版本）；
4. 运行一致性校验（`--strict-count`），必须 PASS；
5. 切换配置（`AUTHENTICATION_BACKENDS` + 中间件），`identity_mode=dual`；
6. 冒烟：三端登录 + 强制改密 + 一个越权拒绝；
7. 观察 10 分钟冲突计数；
8. 通过则进入 72 小时观察期。

## 5. 监控指标（切换期）

| 指标 | 采集方式 | 阈值 |
|---|---|---|
| 登录失败率 | 应用日志 | > 5% 告警 |
| `conflict` 身份数 | 审计表统计 | > 0 立即排查（正常应为 0） |
| 登录限速触发数 | `LoginAttempt` | 突增 10 倍告警 |
| 5xx 比例 | Web 服务器 | > 0.5% 回滚 |
| 回填不一致项 | 一致性校验 | > 0 回滚 |

## 6. 回滚触发阈值与动作

| 触发条件 | 动作 |
|---|---|
| 冲突身份出现 | 停止切换，回退中间件 |
| 登录成功率 < 95% | 立即回退配置（不改数据） |
| 一致性校验 FAIL | 停止，不清库，人工分析 |
| 数据库连接错误 1040 | 扩容连接或回退 |

回滚只涉及**配置切换**（不改数据），因此可在 2 分钟内恢复。

## 7. 数据反向同步 / 丢失防护

| 场景 | 方案 |
|---|---|
| 切换期新增学生 | 双写服务（`dual_write.create_student`）保证两表一致 |
| 切换期改密 | `dual_write.change_password`（哈希同源） |
| 回滚后新增数据 | 旧表仍是权威（路径 A 只新增 Account，不删旧表） |
| 回滚丢失风险 | 若新表独有数据（如 RBAC 角色），回滚后保留但不再使用 |

## 8. 验收与观察期

| 阶段 | 时长 | 通过标准 |
|---|---|---|
| 冒烟 | 10 分钟 | 三端可登录、无冲突 |
| 观察期 | 72 小时 | 错误率正常、无 `conflict`、一致性校验 PASS |
| 收尾 | 观察期后 | 决定是否把 `identity_mode` 改为 `account` |

## 9. 负责人（待填）

| 角色 | 姓名 | 职责 |
|---|---|---|
| 切换执行 | — | 执行步骤 1–5 |
| 数据核对 | — | 一致性校验 |
| 回滚决策 | — | 阈值判定 |
| 业务确认 | — | 冒烟验收 |

> 本 Runbook **未被执行**，仅为评审材料。
