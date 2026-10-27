# SMASS R2.1 变更清单（Change Log）

- 分支：`feat/smass-r21-account-rbac`（基点 `c97053b`）
- 提交：`c97053b` → `9ea257f`（G0/G1）→ `335ab85`（G2/G4）→ 收尾提交（G3/报告）
- 未推送远程；工作区以最终 `git status` 为准

## 1. 新增代码

| 文件 | 作用 |
|---|---|
| `r21_account/__init__.py` / `apps.py` | 原型 app（仅 `settings_r21` 加载） |
| `r21_account/models.py` | Account / AccountRole / LegacyAccountLink / StudentProfile / TeacherProfile / AccountAuditLog / LoginAttempt |
| `r21_account/backends.py` | `AccountBackend(ModelBackend)` |
| `r21_account/services.py` | 角色-权限同步、限速、密码策略、审计、临时口令 |
| `r21_account/permissions.py` | 权限矩阵 + `dangerous_bulk_delete` 默认无人 |
| `r21_account/scoping.py` | 对象级范围（默认拒绝） |
| `r21_account/middleware.py` | 强制改密中间件 |
| `r21_account/views.py` | 登录/注销/首页/改密/受保护探针 |
| `r21_account/dual_write.py` | 双写服务（单事务、哈希同源） |
| `r21_account/management/commands/backfill_accounts_r21.py` | 回填（dry-run/since/rollback/幂等/撞号） |
| `r21_account/management/commands/verify_account_consistency.py` | 一致性校验 |
| `r21_account/migrations/0001_initial.py` | 7 模型 + 约束 |
| `r21_account/tests/*`（6 文件） | 60 例 |
| `smass/settings_r21.py` / `smass/urls_r21.py` | 隔离配置与路由 |
| `templates/r21/{login,home,change_password}.html` | 三端共用认证页面 |

## 2. 未修改（重要）

| 项 | 说明 |
|---|---|
| `app01/*` | **零改动**（旧表、视图、表单、中间件均未变） |
| `smass/settings.py` | 未改（正式配置不含 `r21_account`） |
| `AUTH_USER_MODEL` | 未改 |
| 既有迁移 | 未重写 |
| `smass` 库 | 未写入（仅 `dumpdata` 只读导出） |
| 两个 R2.0 原型库 | 未删除、未修改 |

## 3. 行为变化（仅限 `settings_r21` 环境）

| 场景 | 变化 |
|---|---|
| 登录 | 改为统一 `Account` + 自定义 backend；`request.user` 为 Account |
| 首次登录 | 强制跳改密页；AJAX 返回 403 `must_change_password` |
| 登录失败 | 持久化计数，同 IP 5 次/15 分钟锁定（HTTP 429） |
| 权限 | 由 `AccountRole` → Group → Permission 判定 |
| 数据可见范围 | 按角色收窄；无角色/无 scope 默认拒绝 |

> 正式 `smass` 环境（`settings.py`）行为**完全没有变化**。

## 4. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 两套用户模型 `related_name` 冲突 | 已显式命名 | 移除 `r21_account` app |
| `app01` 中间件与统一认证冲突 | `settings_r21` 已移除旧中间件 | 恢复中间件列表 |
| 回填撞号 | 冲突检测 + 跳过不覆盖 | `--rollback` |
| 双写半成功 | 单事务 + 故障注入测试 | 事务自动回滚 |
| 限速误锁 | 主维度含 IP，账号阈值更高 | 删除 `LoginAttempt` 记录 |
| 原型库膨胀 | 独立库 | `DROP DATABASE smass_r21_proto`（**属受控操作，本轮未执行**） |

## 5. 遗留（NOT DONE / REQUIRES AUTHORIZATION）

1. 正式库账号读写切换；
2. `AUTH_USER_MODEL` 变更；
3. `app01` 视图接入 RBAC 与强制改密；
4. 旧表清理（需独立评审 + 可证明回滚）；
5. 双写一致性定时任务；
6. 多实例共享限速存储；密码历史。
