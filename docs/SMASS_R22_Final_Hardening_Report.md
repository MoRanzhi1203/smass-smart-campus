# SMASS R2.2 Final Hardening 报告

- 基线：`feat/smass-r22-g6-g8-readiness` @ `d24b786`
- 分支：`feat/smass-r22-final-hardening`
- 执行时间：2026-10-28
- **终态：GO_RECOMMENDED（带三项前置条件）**

## 1. 阶段状态

| 阶段 | 状态 | 关键证据 |
|---|---|---|
| H0 基线 | **PASS** | 267 基线全绿；`max_connections=20`；smass 26 表 / 1-3-2 未变 |
| H1 审计批次 | **PASS** | 11 例；批次 ID + 回滚追加事件 + 因果链 |
| H2 切换演练 | **PASS** | `smass_r22_g8_drill`：切换后写入全部保留、故障注入回滚、批次链完整 |
| H3 旧业务兼容 | **PASS** | 7 例；`/admin/student/list/` 真实页面 200 |
| H4 冲突告警 | **PASS** | 6 例；结构化告警 + 阈值抑制 + 无敏感字段 |
| H5 并发/浏览器 | **PARTIAL** | 并发边界实测 20；10000 规模与 Firefox/WebKit NOT RUN |
| H6 验收 | **PASS** | 全量回归 + 报告 + 提交 |

## 2. P0 四项阻断问题的处理结果

### 2.1 审计批次追溯（H1）— 已解决

新增 `AccountAuditEvent` 字段：`batch_id` / `operation` / `source_batch_id` / `counts`（迁移 `0002`）。

- 每次回填生成唯一 `batch_id`，记录**脱敏计数**（只有整数，无姓名/哈希）；
- 回滚**追加** `operation='rollback'` 事件，`source_batch_id` 指向被回滚的回填批次；
- 重复回滚产生多个 rollback 批次，**历史不删除**；
- `find_unbatched_backfill()` 用于对账"有业务数据但无批次事件"的崩溃窗口。

### 2.2 G8 完整切换与回滚演练（H2）— 已解决

新建 `smass_r22_g8_drill`（全合成，100 账号）：

| 步骤 | 结果 |
|---|---|
| 切换（off → dual）五类身份 | account/legacy/dual/conflict/anonymous **全部正确** |
| 切换后写入（建号/改密/授角色/停用） | 全部成功 |
| 故障注入（事务中途抛错） | 账号**未持久化**（回滚生效） |
| 回滚（dual → off） | 计数完全保留（101/101/102/101） |
| 切换期数据存活 | 新账号 ✓、改密 ✓、角色 ✓、停用 ✓ |
| 权限提升检查 | conflict 被拒 ✓ |
| 批次审计 | chain_len=2、unbatched_flag=false |

### 2.3 旧业务兼容（H3）— 已解决

`r22_account/legacy_compat.py`：把 Account 经 `LegacyAccountLink` 映射为等价 `session['info']`，
在 `/admin/`、`/student/`、`/teacher/` 前缀上按需桥接。**app01 零改动**。

发现的真实缺陷：桥接写入 session 后，身份解析**缓存未失效**，导致 RoutePolicy 仍按旧
`account` 判定并拒绝旧路由（302）。修复为桥接后清空缓存键，身份变为 `dual` 后放行。

### 2.4 冲突告警（H4）— 已解决

`r22_account/alerts.py`：统一 `smass.security` logger，白名单字段，阈值抑制。

| 事件 | 阈值 |
|---|---|
| `identity_conflict` | 60s / 1 次（冲突必须立即可见） |
| `disabled_account` | 60s / 10 次 |
| `bulk_auth_failure` | 60s / 20 次 |
| `audit_failure` | 60s / 1 次 |

测试验证：告警可见、无敏感字段、阈值抑制有效、conflict 请求既被拒又告警。

## 3. 并发与容量（H5）

| 并发 | 成功 | 说明 |
|---|---|---|
| 1 | 5/5 | — |
| 10 | 50/50 | — |
| **20** | **100/100** | 恰好达到 `max_connections=20` |
| 50 | 143/250 | `OperationalError:1040`（连接数耗尽） |

**结论：当前 MySQL `max_connections=20`，安全并发上限就是 20。** 超过即建连失败（事务未开始，无半写数据）。
生产若需 > 20 并发，必须先扩容或引入连接池——这是正式切换的**硬前置条件**。

## 4. 测试

| 套件 | 用例 | 结果 |
|---|---|---|
| r22（G2–G7 + H1/H3/H4） | 89 | PASS |
| r21 | 72 | PASS |
| app01 | 114 | PASS |
| e2e | 16 | PASS |
| **合计** | **291** | 全绿 |

新增 24 例（H1 11 + H3 7 + H4 6）。

## 5. 未完成

| 项 | 状态 |
|---|---|
| 10,000 账号规模 | **NOT RUN** |
| Firefox / WebKit | **NOT RUN**（未安装） |
| 审计保留策略实现 | 仅提案（不自动删除） |
| 库/账号清理 | 仅提案（需授权） |
| 正式切换 | **NOT AUTHORIZED** |

## 6. 结论

P0 四项全部实证通过，回滚无数据丢失且审计可追溯。**GO_RECOMMENDED**，但附三项条件：

1. 扩容 `max_connections` 或引入连接池（并发 > 20 会失败）；
2. 补测 10,000 规模（当前只有 1,146 合成账号）；
3. 若需跨浏览器保证，先装 Firefox/WebKit。

**GO 仅表示建议申请正式切换授权，本轮未执行、也未获得任何切换授权。**
