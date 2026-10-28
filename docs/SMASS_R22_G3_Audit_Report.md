# SMASS R2.2 G3 报告（审计与 admin 日志解耦）

- 阶段：G3（解决 L1 审计外键冲突）
- 测试：`r22_account/tests/test_g3_audit.py`（**13 例，全 PASS**）
- 新模型：`r22_account.AccountAuditEvent`（独立表，不改 R2.1 的 `AccountAuditLog`）

## 1. 为什么必须解耦

G1 实测：`django_admin_log.user_id` 外键指向 `auth_user(id)`。
以 `Account.pk` 写 `LogEntry` 会：

- `auth_user` 无该 id → `IntegrityError`（500）；
- 两表 pk 都是自增整数，**同号时记到错误人名下**（数据完整性事故）。

因此 R2.2 的账号审计**完全绕开** `django_admin_log`，写入自己的表。

## 2. 模型字段

| 字段 | 作用 |
|---|---|
| `action` | 动作名（如 `role_grant`） |
| `outcome` | `success` / `denied` / `error` —— 明确区分结果 |
| `actor_kind` | `account` / `legacy` / `system` / `unknown` |
| `actor_login` | 可为空；**未知操作者就留空，不伪造 auth.User** |
| `target` / `target_id` | 目标类型与标识 |
| `context` | 已脱敏 JSON |
| `ip` / `request_id` | 来源与请求关联 |
| `created_at` | 时间 |

## 3. 事务语义（关键）

| 场景 | 行为 | 验证 |
|---|---|---|
| 业务成功 | 审计与业务**同一事务**提交 | `test_business_and_audit_commit_together` |
| 业务失败 | 业务回滚，审计以 `outcome=error` 在回滚后**独立写入** | `test_business_failure_rolls_back_but_audit_survives` |
| 主动拒绝 | `outcome=denied` | `test_denied_event` |
| 审计关闭 | 抛 `AuditDisabled`，不静默跳过 | `test_audit_disabled_raises` |

关键断言（业务失败场景）：

```
业务对象不存在（已回滚） + 审计存在且 outcome='error'
```

即：**绝不把失败记成成功**。

## 4. 脱敏

`sanitize()` 剔除的键（大小写不敏感）：`password|passwd|pwd|hash|token|secret|session|card_id|id_card|phone|otp`。

实测：

```python
sanitize({'password': ..., 'token': ..., 'card_id': ..., 'safe_key': 'keep-me'})
== {'safe_key': 'keep-me'}
```

写入时也会再脱敏一次（`test_event_context_is_sanitized_at_write`）。

## 5. 与 admin 日志的关系（实测）

| 测试 | 结论 |
|---|---|
| `test_audit_does_not_touch_admin_log_when_pk_collides` | 构造 `auth_user.pk == Account.pk` 最坏情形，审计后 `LogEntry` 计数不变 |
| `test_audit_works_when_no_matching_auth_user` | 无同名 auth_user 时审计照常，且不写 admin log |
| `test_admin_log_would_fail_for_account_pk` | **反证**：绕过审计直接写 admin log 会 `IntegrityError` |

## 6. 操作者语义

| actor | actor_kind | actor_login |
|---|---|---|
| `Account` | `account` | 登录名 |
| legacy dict | `legacy` | 旧 id |
| `None` | `unknown` | 空字符串（不编造） |
| 其它 | `system` | 截断字符串 |

## 7. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 失败审计也丢失（事务已回滚） | 用独立写入，事务外记录 | — |
| 审计表膨胀 | 索引 + 后续清理策略（G5+） | 关闭 `audit_enabled` |
| 敏感值混入 context | 写入时强制 sanitize + 测试 | — |
| 与 R2.1 `AccountAuditLog` 重复 | 明确边界：R2.1 用于账号内部；R2.2 用于兼容层事件 | 移除 `r22_account` |

## 8. 未做

| 项 | 状态 |
|---|---|
| 审计查询/导出界面 | NOT DONE |
| 审计保留策略与归档 | NOT DONE（G5+） |
| 把 G3 审计接入 `app01` 业务写操作 | NOT DONE（正式路径未切换） |
