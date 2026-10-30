# S15 API 安全（scope、幂等、令牌吊销、限流、重放防护）

> 状态：**TESTED**（28 例：服务 20 + 端点 7 + 页面 1 + Chromium E2E 1，共 28）
> 代码：`smass_api_security/`、`templates/s15/`、`smass/settings_s15.py`、`smass/urls_s15.py`
> 隔离库：`smass_s15_api`；示例端点 `/s15/api/v1/ping`、`/s15/api/v1/students/count`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 令牌认证 | `Authorization: Bearer`，库中只存 SHA-256 | `test_token_stored_hashed`、`test_authenticate_ok` |
| 令牌异常 | 缺失/无效/过期/吊销分别返回 401 + 原因码 | `test_missing_token`、`test_bad_token`、`test_expired_token`、`test_revoked_token` |
| scope | 端点声明 scope，令牌无该 scope 返回 403 | `test_scope`、`test_scope_denied` |
| 限流 | 令牌 + 固定窗口计数，超限 429 | `test_rate_limit`、`test_rate_limited` |
| 幂等 | `Idempotency-Key` 命中返回缓存响应并标记头 | `test_idempotent_replay_returns_cached` |
| 幂等冲突 | 同键不同请求体返回 409 | `test_idempotency_conflict` |
| 必填幂等键 | 声明幂等的端点缺键返回 400 | `test_missing_idempotency_key` |
| 重放防护 | `X-Timestamp` ±300 秒 + `X-Nonce` 一次性 | `test_replay_detected`、`test_stale_timestamp`、`test_replay_blocked` |
| 审计 | 每次请求写 `ApiRequestLog`（append-only） | `test_request_logged`、`test_request_log_visible` |
| 管理页面 | 创建客户端、签发令牌（仅显示一次）、吊销、日志 | `test_admin_creates_client_and_token`、`test_admin_revokes_token`、浏览器 E2E |
| 权限 | 只有管理员可管理；学生 403 | `test_create_client_requires_admin`、`test_student_forbidden` |

## 2. 设计要点

- **装饰器统一入口**：`@api_endpoint(scope, limit, idempotent)` 依次处理认证 → scope →
  重放 → 限流 → 幂等 → 业务 → 审计，任何一步失败都写日志；
- **哈希存储**：令牌只存 SHA-256，明文仅在签发时展示一次；
- **幂等基于请求摘要**：`sha256(method|path|body)`，同键不同体判为冲突（409）；
- **重放双层**：时间窗（±300s）挡住旧请求，nonce 唯一约束挡住重发；
- **保存点隔离**：`Nonce`/`IdempotencyKey` 的唯一冲突在 savepoint 内捕获，
  不会污染外层事务（本轮修复的真实问题）。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_api_security --settings=smass.settings_s15 --noinput
```

实测（2026-10-30）：**28 例 OK**（服务 20 + 端点 7 + 页面 1 + Chromium E2E 1）。

## 4. 已知边界

1. 限流为固定窗口计数，边界处可能有 2 倍突发；生产可换滑动窗口/Redis；
2. nonce 表未做定期清理（需要保留期任务，可接 S13 的保留控制）；
3. 幂等缓存无过期，长期运行需 TTL 清理；
4. 示例端点只用于验证机制，未对真实业务 API 全量套用（接入时复用装饰器即可）。
