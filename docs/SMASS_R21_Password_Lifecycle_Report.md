# SMASS R2.1 账号生命周期报告（Password Lifecycle Report）

## 1. 首次登录强制改密（三端统一）

中间件：`r21_account/middleware.py::ForcePasswordChangeMiddleware`

| 行为 | 实测 |
|---|---|
| 页面访问被拦截 | `302 → /r21/change-password/` |
| AJAX 访问 | `403 {"code": "must_change_password"}` |
| 白名单 | 改密页 / 注销 / 登录 / static / media 可访问 |
| 覆盖范围 | **三端共用**（统一 Account，无"某端漏做"） |

浏览器实测（`test_browser_r21.py`，4 例 PASS）：

| 角色 | 登录 → 强制改密 → 改密 → 首页 |
|---|---|
| 管理员 `E2E001` | PASS |
| 教师 `E2E002` | PASS |
| 学生 `E2E003` | PASS |
| 弱密码 `123456` | 被拒，原密码仍有效（PASS） |

## 2. 临时口令

`services.set_temporary_password()`：设密码并置 `must_change_password=True`，写审计，
**不记录明文**。

## 3. 密码策略

- 统一 `django.contrib.auth.password_validation.validate_password`
- 下限 `MinimumLengthValidator(min_length=6)`，**取消 6-10 位上限**（20 位强密码通过，有测试）
- 常见口令 / 纯数字 / 过短均被拒（3 例测试）
- 学生端上限调整：R2.1 原型已生效；`app01` 现有视图的规则调整与"正式切换"同批，避免半切换

## 4. 会话与改密

| 场景 | 行为 | 证据 |
|---|---|---|
| 自助改密 | `update_session_auth_hash()`，当前会话不被登出 | 浏览器 PASS |
| 他处改密/重置 | 旧会话的 `get_session_auth_hash` 不匹配 → 失效 | `test_password_change_invalidates_old_session` PASS |
| 注销 | `logout()` 清 session | PASS |
| `next` 重定向 | R2.1 原型登录固定跳 `/r21/home/`，无外部 `next` 参数，**不存在开放重定向面** | — |

## 5. 持久化登录限速

模型：`LoginAttempt(login_name, ip, success, created_at)`

| 维度 | 阈值 | 目的 |
|---|---|---|
| `(login_name, ip)` | 5 次 / 15 分钟 | 防止单人暴力破解 |
| `(login_name)` | 20 次 / 15 分钟 | 防分布式撞库 |
| 锁定 | 900 秒（时间窗滑动） | 自动过期，无需定时清理 |

测试（`test_rate_limit.py`）：
- 同 IP 5 次后 **429**；
- **新 client（等价新会话）仍被锁**（跨会话有效）；
- 其他 IP 不受同一 IP 封锁影响（避免恶意锁死他人账号）；
- 跨 IP 累计 20 次触发账号级锁定；
- 失败记录超出时间窗后自动解除；
- 成功登录 + `clear_login_failures` 清理。

## 6. 未做

| 项 | 状态 |
|---|---|
| 把强制改密应用到 `app01` 现有三端页面 | **NOT DONE**（正式路径未切换） |
| 限速的分布式共享（多进程/多实例） | 未做（当前依赖数据库，单实例足够；多实例需共享存储，已具备表结构） |
| 密码历史（禁止复用最近 N 次） | 未做 |
