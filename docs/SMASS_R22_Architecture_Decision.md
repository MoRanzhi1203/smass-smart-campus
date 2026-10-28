# SMASS R2.2 架构决策（G1 Architecture Decision）

- 决策主题：R2.2 正式账号接入应采用哪条技术路径
- 证据来源：`docs/SMASS_R22_Compatibility_Audit.md`（12 例，另有 R2.1 的 60 例）
- 结论：**继续采用路径 A（自定义 Backend，不改 `AUTH_USER_MODEL`）**，但必须接受并处理三项已知限制
- 正式切换：**NOT DONE / REQUIRES EXPLICIT AUTHORIZATION**

## 1. 两条路径的实测对比

### 路径 A：继续用 `AccountBackend`，`AUTH_USER_MODEL` 保持 `auth.User`

| 维度 | 实测 |
|---|---|
| 认证链路 | 可用（R2.1 13 例 + R2.2 12 例） |
| `request.user` | 类型为 `Account`（真实 HTTP 请求断言） |
| 权限体系 | `has_perm`/`has_module_perms`/Group 全部可用 |
| 会话哈希 | 改密后旧会话失效 |
| 与 Django admin log | **不兼容**（`django_admin_log.user_id` FK 指向 `auth_user`，写日志抛 `IntegrityError`） |
| 与 `get_user_model()` 组件 | **不兼容**（仍返回 `auth.User`） |
| 迁移影响 | **零**（不改 `AUTH_USER_MODEL`，不新增 auth 相关迁移） |
| 回滚 | 容易（移除 app + 切回旧中间件） |
| 需要的工作 | 自建审计、避免依赖 admin log、隔离 `AUTH_USER_MODEL` 组件 |

### 路径 B：正式切换 `AUTH_USER_MODEL`

| 场景 | 实测结果 |
|---|---|
| **全新库** + app01 + 自定义用户模型 | **PASS**（`smass_r22_b_proto`：`migrate` 成功，`check` 0 issues） |
| **已有 `auth_user` 数据的库**中途切换 | **FAIL（硬阻断）** |

路径 B 中途切换的实测错误：

```
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration admin.0001_initial is applied before its dependency
proto_user_model.0001_initial on database 'default'.
```

同时探测到的后果（`scripts/r22_b_switch_probe.py`）：

| 探测项 | 实测 |
|---|---|
| `AUTH_USER_MODEL` | `proto_user_model.ProtoUser`（配置已切换） |
| `get_user_model()` | `proto_user_model.protouser` |
| 表清单 | 只有 `auth_user`、`django_admin_log`；**新用户表未创建** |
| `django_admin_log` 外键 | **仍指向 `auth_user.id`**（未随配置重建） |
| 旧 `auth_user` 数据 | 仍在，**不会被自动迁移** |

即：切换 `AUTH_USER_MODEL` **只改变 Django 的运行时认知，不改变既有表结构**。
要真正完成切换，必须额外做：

1. 反向迁移 `admin`（丢弃 admin log）或伪造 `django_migrations` 记录；
2. 重建 `django_admin_log`、`auth_permission` 等依赖表；
3. 迁移/合并 `auth_user` 数据到新表；
4. 处理第三方 app 的 `AUTH_USER_MODEL` 依赖。

每一项都不可逆或高风险。

## 2. 决策

**采用路径 A。** 理由（按权重）：

1. **迁移成本为零**：不触碰 `AUTH_USER_MODEL`、不重建任何 auth 表，`app01` 与既有数据完全不动；
2. **路径 B 有硬阻断**：`InconsistentMigrationHistory` 是 Django 主动拒绝，不是配置可绕过；
3. **可回滚性**：路径 A 移除 app 即可回退；路径 B 需要重建库；
4. 路径 A 的已知限制**都可以在应用层规避**（见 §3）。

**保留路径 B 作为长期终态选项**，但前提是"重建库 + 停机迁移"，属于 R3 级别工程，不属于 R2.2。

## 3. 路径 A 的三项限制与处理方案（G2–G4 必做）

| # | 限制 | 处理方案 | 阶段 |
|---|---|---|---|
| L1 | `django_admin_log` FK 指向 `auth_user` | ① 不使用 Django admin（本项目本来就没挂 `admin.site.urls`）；② 全部审计走 `r21_account.AccountAuditLog`（已实现）；③ 若未来必须用 admin，则先建"影子 auth_user"或改写 LogEntry 路由 | G3 |
| L2 | `get_user_model()` 仍是 `auth.User` | 内部代码一律用 `r21_account.models.Account` 或 `settings.R22_ACCOUNT_MODEL` 常量；禁止业务代码调用 `get_user_model()`；加静态检查 | G2 |
| L3 | 两套身份（`session['info']` 旧机制 vs `request.user`）并存 | 切换期做**双读**：`request.account` 兼容层优先取 `request.user`，回退 `session['info']`；两者不一致时以 `request.user` 为准并记录告警 | G4 |

## 4. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| 切换期双身份冲突（session['info'] vs request.user） | 高 | 授权错乱 | G4 双读兼容层 + 告警日志 + 交叉校验 | 关闭兼容层，回退旧中间件 |
| 误用 `get_user_model()` 导致拿到 auth.User | 中 | 逻辑错误/权限错乱 | G2 静态检查（禁止该调用）+ 代码评审 | 修改代码 |
| 第三方 app 依赖 `AUTH_USER_MODEL` | 中 | 功能异常 | G2 依赖清单审计（当前仅 Django 内置） | 移除该 app |
| 回填/双写遗漏导致数据分叉 | 中 | 数据不一致 | G5 一致性校验 + 定时任务 | `--rollback` |
| 旧表 `app01` 与新表并存期过长 | 中 | 技术债 | 明确清理窗口（G8 门禁） | — |
| 切换后无法回滚 | 低（路径 A） | 高 | 路径 A 天然可回滚；不做不可逆迁移 | 移除 app |
| 性能退化（双读/双写） | 低 | 中 | G6 查询数基准 | 回滚开关 |

## 5. 明确不实施（本轮及后续均需单独授权）

| 项 | 状态 |
|---|---|
| 修改 `AUTH_USER_MODEL` | 未做 |
| 修改 `smass` 库数据 | 未做 |
| 切换 `app01` 认证路径 | 未做 |
| 删除旧表 / 既有原型库 | 未做 |
| 重写既有迁移 | 未做 |
| 推送远程 | 未做 |
