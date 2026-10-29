# SMASS R10 Password Lifecycle Report（H1）

- 设置：`smass.settings_r10`
- 测试：`smass_operations/tests/test_r10_h1_password.py`（18 例）
- 结果：**18/18 PASS**

## 1. 根因（H0 审计发现）

计划把 R-03 描述为"`/r21/change-password/` 占位重定向"。审计发现真相比这更严重：

| 组件 | 状态 |
|---|---|
| `r21_account/views.py::change_password_view` | **完整实现**（当前密码校验、4 项强度策略、`set_password`、`update_session_auth_hash`） |
| `r21_account/middleware.py::ForcePasswordChangeMiddleware` | **已在 `settings_r10` 的 MIDDLEWARE 中** |
| `templates/r21/change_password.html` | 存在 |
| `r21_account/tests/test_password_lifecycle.py` | **14 例，在 `settings_r21` 下全过** |
| `smass/urls_r10.py` 第 27 行 | **`RedirectView(url='/r10/')`** ← 唯一的问题 |

**结论**：功能完整，但 R10 这一套 URLconf 用 `RedirectView` 把它整个替换掉了。
后果：任何 `must_change_password=True` 的账号访问改密页会被立刻送走，
**强制改密在整个 R10 站点上完全失效**。

## 2. 修复

```python
# smass/urls_r10.py
- path('r21/change-password/', RedirectView.as_view(url='/r10/'), ...)
+ path('r21/change-password/', r21_views.change_password_view,
+      name='r21_change_password')
```

一行。但这行决定了强制改密是"生效"还是"形同虚设"。

## 3. 验证（18 例）

### 3.1 路由不再占位

| 测试 | 断言 |
|---|---|
| `test_get_renders_real_form` | 页面含 `name="current_password"/new_password/confirm_password"` |
| `test_no_longer_redirects` | 状态码不是 301/302 |
| `test_anonymous_redirected_to_login` | 匿名 → 302 到 `/r21/login/` |

### 3.2 强制改密生效

| 测试 | 断言 |
|---|---|
| `test_other_pages_redirect_to_change_password` | `/r10/` `/r4/units/` `/r7/dashboard/` 全部 302 → 改密页 |
| `test_ajax_gets_403_json` | AJAX → **403** + `code=must_change_password` |
| `test_change_page_itself_allowed` | 改密页本身 200（避免重定向死循环） |
| `test_logout_allowed_while_forced` | 登出放行（用户能退出） |
| `test_change_then_redirect_target_reachable` | 改密后业务页 200 |

### 3.3 校验与安全

| 测试 | 断言 |
|---|---|
| `test_wrong_current_password_rejected` | 旧密码错 → 拒绝，哈希不变 |
| `test_mismatch_rejected` | 两次输入不一致 → 拒绝 |
| `test_same_as_current_rejected` | 新密码等于旧密码 → 拒绝 |
| `test_weak_password_rejected` | `123` → 拒绝，**哈希不变**（行为断言，不依赖文案） |
| `test_short_password_rejected_by_length_validator` | `Ab1!` → 拒绝 |
| `test_successful_change_updates_hash` | 哈希改变；新密码可登录；旧密码不可 |
| `test_password_not_echoed_in_response` | 响应不回显新旧密码 |
| `test_post_without_csrf_rejected` | 缺 CSRF → 403 且不改密 |

### 3.4 多会话

| 测试 | 断言 |
|---|---|
| `test_current_session_survives` | 改密后当前会话仍可访问业务页 |
| `test_other_session_invalidated` | **其他会话失效** |

**其他会话为什么自动失效**：Django 的 `AuthenticationMiddleware` 每次请求比对
`session['_auth_user_hash']` 与 `user.get_session_auth_hash()`。
密码变更 → HMAC 改变 → 旧会话的 `request.user` 降级为匿名。
这是内置机制，无需自建 session 清理。

## 4. 一个测试方法学问题

弱密码测试最初写的是：

```python
self.assertIn('太短', body)      # 失败
```

因为项目 `LANGUAGE_CODE` 是英文，Django 返回 `"This password is too short."`。

改为行为断言：

```python
old_hash = Account.objects.get(pk=...).password
self._post(PASSWORD, '123', '123')
new_hash = Account.objects.get(pk=...).password
self.assertEqual(old_hash, new_hash)   # 与语言无关
```

**教训**：测试断言状态变化，不要断言提示文案。

## 5. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 旧 MD5 哈希升级 | **NOT RUN** | `smass` 的 `app01_*` 密码格式未验证；需要真实哈希样本（PII 授权） |
| 管理员重置临时密码流程 | **PARTIAL** | `must_change_password` 标记存在且生效；重置入口未做 UI |
| 密码历史（禁止复用旧密码） | **NOT RUN** | 未实现，属策略项 |
| 登录失败锁定阈值调优 | **PARTIAL** | 限速存在；阈值未按业务策略校准 |

## 6. 与计划的对应

| 计划要求 | 本报告 |
|---|---|
| 真实 GET/POST，非占位 | §2 §3.1 |
| 中间件白名单、避免重定向循环 | §3.2（改密页/登出放行） |
| CSRF、旧密码校验、强度、长度、重复一致 | §3.3 |
| 不回显、不记录密码 | §3.3 |
| 会话哈希更新、其他会话失效 | §3.4 |
| 管理员重置与临时密码 | §5（PARTIAL） |
| 旧哈希兼容 | §5（NOT RUN，需 PII 授权） |
| 三角色、首登、错误路径、CSRF、直接 URL | §3 |
