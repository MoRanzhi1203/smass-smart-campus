# SMASS R2.2 后续任务清单（G2–G8 Readiness Roadmap）

> 本清单只描述**将要做什么**与**验收标准**。未经后续明确授权，不得进入 G5 之后的正式接入/迁移。
> 所有阶段均在隔离库 `smass_r22_*`（或既有 `smass_r21_proto`）中开发，`smass` 保持只读。

## 命名与边界约定

| 项 | 约定 |
|---|---|
| 开发库 | `smass_r22_proto`（待建）、可复用 `smass_r21_proto` |
| 正式库 | `smass` **只读** |
| 原型库 | `smass_proto_*`、`smass_r21_proto`、`smass_r22_*` 均**不删除** |
| 正式切换 | `AUTH_USER_MODEL` 不改；`app01` 读写路径不切，除非 G8 门禁全部通过且获单独授权 |

## G2：认证适配层与"禁止误用默认用户模型"约束

| 项 | 内容 |
|---|---|
| 目标 | 建立 `request.account` 访问契约；禁止业务代码使用 `get_user_model()` |
| 文件 | `r22_account/`（新 app 或复用 `r21_account`）、`app01/utils/authz.py` 兼容层 |
| 命令 | `manage.py check`、`manage.py test r22_account` |
| 测试用例 | ① `request.account` 在三类视图可用；② 未登录时为 None；③ 静态扫描（grep）证明 `app01` 无 `get_user_model()` 调用 |
| 验收 | 用例全绿 + 静态检查零命中 |
| 风险/回滚 | 低；回滚=移除兼容层 |

## G3：审计与 Django admin 解耦

| 项 | 内容 |
|---|---|
| 目标 | 解决 L1（admin log FK 指向 auth_user） |
| 方案 | ① 确认 `admin.site.urls` 未挂载（现状成立）；② 所有敏感操作写 `AccountAuditLog`；③ 增加测试：以 `Account` 身份触发一个 admin 动作，断言 **不写** `django_admin_log` 且审计落在 `AccountAuditLog` |
| 命令 | `manage.py test r22_account.tests.test_audit_decoupling` |
| 验收 | 无 `IntegrityError`，审计表有记录 |
| 风险/回滚 | 低 |

## G4：双身份兼容层（session['info'] ↔ request.user）

| 项 | 内容 |
|---|---|
| 目标 | 解决 L3：切换期 `app01` 旧 `session['info']` 与 `request.user` 并存 |
| 方案 | `r22_account/compat.py::current_identity(request)`：优先 `request.user`，回退 `session['info']`；两者不一致 → 以 `request.user` 为准 + 写 `identity_conflict` 审计 |
| 文件 | `r22_account/compat.py`、`app01/middleware/auth.py`（只读改造，隔离分支） |
| 测试用例 | ① 仅旧 session；② 仅新 user；③ 两者一致；④ 两者冲突（断言以新为准 + 告警）；⑤ 都无 → 匿名 |
| 验收 | 5 类场景全绿；冲突有审计 |
| 风险/回滚 | 中；回滚=关闭兼容层，恢复旧中间件 |

## G5：正式库回填演练（只读源 + 隔离克隆）

| 项 | 内容 |
|---|---|
| 目标 | 用 `smass` 的**只读克隆**验证正式数据回填可行性 |
| 方案 | `mysqldump smass` → 恢复到 `smass_r22_rehearsal` → 在克隆库上跑 `backfill_accounts_r21` + `verify_account_consistency --strict-count` |
| 命令 | `scripts/db_backup.ps1`（源 smass）、`db_restore_drill`（改名或新增只读克隆模式）、回填命令 |
| 验收 | 克隆库回填后：账号数=旧表行数、哈希逐条一致、角色匹配、0 冲突 |
| 风险/回滚 | 中；克隆库可丢弃 |
| 备注 | 需要新增"克隆到指定库名"的能力，现有 `db_restore_drill` 会自动 DROP，需评估复用或新增 |

## G6：性能与容量基线

| 项 | 内容 |
|---|---|
| 目标 | 量化双读/双写带来的查询数与耗时变化 |
| 方案 | `CaptureQueriesContext` 对比：切换前 vs 双读兼容层；记录 `smass` 实际数据规模 |
| 验收 | 查询数增量 ≤ 1/请求；无 N+1 回归 |
| 风险 | 低 |

## G7：浏览器 E2E 全流程（三端 + 旧 URL）

| 项 | 内容 |
|---|---|
| 目标 | 证明切换后旧 URL 仍可用、三端登录/改密/权限拒绝正常 |
| 方案 | Playwright：① 三端登录（新 Account）；② 旧 `/admin/...` URL 经兼容层可用；③ 越权被拒；④ 强制改密；⑤ 注销 |
| 验收 | 全部 PASS；失败截图留档 |
| 风险 | 中（依赖兼容层质量） |

## G8：切换门禁清单与评审材料

| # | 门禁 | 通过条件 |
|---|---|---|
| 1 | 架构决策已评审 | `SMASS_R22_Architecture_Decision.md` 被确认 |
| 2 | G2–G4 完成 | 兼容层 + 审计解耦 + 双身份 全部测试通过 |
| 3 | G5 克隆演练通过 | 回填一致性 100% |
| 4 | G6 性能无退化 | 查询数增量 ≤ 1 |
| 5 | G7 E2E 全绿 | 三端 + 旧 URL |
| 6 | 回滚演练 | 关闭兼容层后系统仍可用 |
| 7 | 备份可恢复 | 切换前全量备份 + 恢复演练 |
| 8 | 清理窗口 | 旧表保留期限与责任人已定 |
| 9 | 值班与观察期 | 切换后 72h 观察指标 |
| 10 | 单独授权 | 用户显式批准正式切换 |

## 建议优先级

1. **G2 → G3 → G4**（基础能力，互相依赖）
2. **G6**（可与 G4 并行，防止性能塌陷）
3. **G5**（需要先有克隆能力）
4. **G7**（依赖 G2–G4）
5. **G8**（最后评审）

## 当前阻断项

| 项 | 状态 | 需要 |
|---|---|---|
| 正式切换 | **NOT DONE** | G8 十项门禁 + 单独授权 |
| `smass` 写入 | **禁止** | 单独授权 |
| `AUTH_USER_MODEL` | **不改** | 单独授权（且 ADR 判定为 R3 级） |
