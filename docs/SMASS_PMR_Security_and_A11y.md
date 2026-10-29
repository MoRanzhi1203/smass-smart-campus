# SMASS PMR Security and A11y Regression（PM8）

- 测试：`smass_operations/tests/test_pmr_pm8_security.py`（23 例，**23/23 PASS**）
- 语境：**迁移**，不是从零交付。重点是"旧结构不能变成新系统里的后门"

## 1. 陈旧 legacy session（本轮核心）

### 背景

`app01` 的旧视图与装饰器读 `session['info']`（见 `r22_account/legacy_compat.py` 注释）。
迁移后若仍有代码信任"只有 `info`、没有 `_auth_user_id`"的 session，
就等于**无凭证访问**。

### 实测

构造只有 `info` 的 session（含伪造姓名 `伪造姓名ZZZ`、`account_id` 指向真实账号），然后请求：

| 端点 | 结果 | 判定 |
|---|---|---|
| `/r4/units/` | 302/403 | 正确拒绝 |
| `/r5/years/` | 302/403 | 正确拒绝 |
| `/r6/tasks/` | 302/403 | 正确拒绝 |
| `/r7/dashboard/` | 302/403 | 正确拒绝 |
| `/r10/` | **200** | **预期**（见下） |

### `/r10/` 返回 200 是设计，不是缺陷

`smass_operations/views.py::nav_home` 的 docstring 明确写：

> 统一入口：展示导航与当前角色，**未登录也可访问（便于排障）**

且实现**完全不读 `session['info']`**：

```python
account = getattr(request, 'user', None)
roles = []
if account is not None and getattr(account, 'is_authenticated', False):
    roles = sorted(account.active_roles())
return render(..., {'account': account if roles else None, 'roles': roles})
```

因此加了两条针对性断言：

| 断言 | 结果 |
|---|---|
| 公开导航页**不得**渲染 `info` 里的名字 | PASS（页面不含 `伪造姓名ZZZ`） |
| 公开导航页**不得**渲染 `info` 里的 id | PASS（不含 `A01`） |
| `request.user` 必须是匿名 | PASS |

**我最初把 `/r10/` 也放进"必须 302/403"的列表，测试失败后才发现是断言写错了**，
不是产品缺陷。已修正断言而不是改代码去迎合测试。

### 已认证时 info 不得覆盖真实身份

| 断言 | 结果 |
|---|---|
| 真实登录后 `request.user.pk` 等于登录账号 | PASS |
| 即使 session 里塞入他人的 `info`，也不被采用 | PASS |

## 2. 强制改密

| 检查 | 结果 |
|---|---|
| `/r10/` `/r4/units/` `/r7/dashboard/` → 302 到改密页 | PASS |
| AJAX → 403 + `code=must_change_password` | PASS |
| 改密页本身 200（无重定向循环） | PASS |
| 登出可达 | PASS |

## 3. 停用账号

| 检查 | 结果 |
|---|---|
| `client.login()` 返回 False | PASS |
| 表单登录停在本页 200，session 无 `_auth_user_id` | PASS |

## 4. CSRF

| 检查 | 结果 |
|---|---|
| 缺 token 的改密 POST → **403** | PASS |
| **且密码哈希未变** | PASS |

## 5. 审计载荷

用 `assertLogs('smass.audit')` 捕获真实日志：

| 断言 | 结果 |
|---|---|
| 不含明文密码 | PASS |
| 不含 `pbkdf2_...$` 编码 | PASS |
| 不含 32 位 MD5 | PASS |
| 保留 `action=` 与事件名 | PASS |

## 6. 跨 settings 路由

| 检查 | 结果 |
|---|---|
| `reverse('r21_change_password')` == `/r21/change-password/` | PASS |
| `reverse('r21_login')` 以 `/r21/login` 开头 | PASS |
| 8 个 settings 文件均存在且含 r21_account 或继承 | PASS |

## 7. Scope 跨面一致（PMR 语境复核）

| 账号 | 服务层 | CSV | R7 指标 |
|---|---|---|---|
| system_admin | 9 | **9** | **9** |
| college_admin(A) | 6 | **6** | **6** |
| college_admin(B)（3 人 < 阈值） | 3 | — | **0 + suppressed** |

与 H6 的结论一致，且在 PMR 语境的测试文件里独立复核。

## 8. 三浏览器矩阵

**本文件不重跑浏览器**。理由与做法：

| 项 | 做法 |
|---|---|
| 实际执行 | H7 已实测：Chromium 6/6、Firefox 10/10、WebKit 每类独立 4/4 |
| 本文件职责 | 断言"U8 套件文件存在且含三引擎"、"E2E 报告记录了 R-15" |
| 不做的 | 不在本文件里声称浏览器跑过——避免用"记录了矩阵"冒充"执行了矩阵" |

## 9. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实 `smass` 数据的会话审计 | **BLOCKED_EXTERNAL_AUTH** | 需真实会话样本 |
| 屏幕阅读器实机 | **NOT RUN** | 无 NVDA/JAWS（继承 H4 结论） |
| axe 自动扫描 | **NOT RUN** | 无离线包（继承 H4） |
| 渗透测试（SQL 注入/XSS 全量） | **NOT RUN** | 超出本轮范围；仅覆盖认证/授权/CSRF |
| 会话固定攻击（session fixation） | **PARTIAL** | `cycle_key()` 存在（`accounts.py`），未单独构造攻击用例 |

## 10. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 跨 settings 认证与 URLconf | §6 |
| 对象/字段 scope 在 UI/API/CSV/R7 一致 | §7 |
| 强制改密、停用、匿名、CSRF | §2 §3 §4 |
| 审计日志敏感载荷扫描 | §5 |
| 合成陈旧 legacy session 不回降 | §1 |
| 三引擎真实执行矩阵，不伪造屏幕阅读器 | §8 |
