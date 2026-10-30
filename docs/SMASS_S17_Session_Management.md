# S17 会话、注销、固定化防护与设备处理

> 状态：**TESTED**（19 例定向测试全通过；旧系统认证 38 例、R21 110 例、R22 117 例回归通过）
> 代码：`app01/services/session_security.py`、`app01/middleware/session_security.py`、
> `app01/views/session_devices.py`、`templates/account/sessions.html`、
> `app01/migrations/0006_login_device.py`
> 测试：`app01/tests/test_s17_session_security.py`

## 1. 验收项与实现对应

| 验收项 | 实现 | 证据 |
|---|---|---|
| 登录后 session 轮换 | `accounts.establish_session()` 首行 `request.session.cycle_key()` | `test_session_key_rotated_on_login`（既有）、`test_login_registers_device_with_server_side_session_key` |
| 注销失效 | `accounts.destroy_session()` 先撤销设备再 `session.flush()` | `test_logout_revokes_device_and_destroys_session`；断言 Session 行被删除、设备 `revoked_at` 非空、后续访问 302 |
| 并发设备管理 | `LoginDevice` 表 + `list_devices/revoke_device/revoke_other_devices` + `/account/sessions/` 页面 | `test_revoke_other_devices_kills_the_other_session`、`test_revoke_specific_device`、`test_device_ids_are_unique_per_login` |
| 空闲超时 | `SessionSecurityMiddleware` + `check_idle_timeout()`，默认关闭 | `IdleTimeoutTests` 4 例（关闭默认、超时 flush、未超时放行、匿名不受影响） |
| 会话固定防护 | 登录 `cycle_key()`；设备标识由服务端生成，绝不接受客户端提交 | `test_login_registers_device_with_server_side_session_key`、`test_cross_role_same_user_id_cannot_be_revoked` |
| CSRF | 破坏性操作仅 POST，由 `CsrfViewMiddleware` 校验 | `test_csrf_is_required_for_mutating_endpoints`（无令牌 403）、`test_mutating_endpoints_reject_get`（GET 405） |
| 越权（IDOR） | 踢出按 `user_id + role + revoked_at IS NULL` 三条件匹配 | `test_student_cannot_revoke_admin_device`、`test_cross_role_same_user_id_cannot_be_revoked` |
| 新旧身份兼容 | `user_id` 一律存字符串，兼容 `auth.User` 整数主键与 R21/R22 账号主键 | `test_identity_compatible_with_string_and_integer_ids` |
| 中间件顺序 | `Session → CSRF → ... → 强制改密 → 空闲超时` | `test_middleware_ordering` |

## 2. 设计要点

### 2.1 设备标识完全由服务端生成

`register_device()` 只在 session 中没有 `device_id` 时生成 `uuid4().hex`，
任何请求参数都无法指定设备标识。踢出时的目标设备也只在**当前账号 + 当前角色**
的记录里查找，因此：

- 无法通过伪造 `device_id` 踢出他人会话；
- 不同角色模型使用相同字符串主键（如 `'001'`）时不会互相越权。

### 2.2 踢出 = 删除服务端 Session 行

`revoke_device()` 直接 `Session.objects.filter(session_key=...).delete()`，
并置 `revoked_at`。即使攻击者持有旧 Cookie，服务端已无对应会话，下一次请求即被拒绝。
当前设备不允许通过该接口踢出，必须走 `/logout/`，避免"把自己锁在页面外"。

### 2.3 空闲超时默认关闭 + 写操作节流

- `SESSION_SECURITY['ENABLED']` 默认 `False`：既有部署升级后行为不变。
- 开启后中间件在**每个已登录请求**上判断是否超时；未超时则按
  `TOUCH_INTERVAL_SECONDS = 60` 节流刷新 `last_activity` 与设备 `last_seen`，
  避免每请求写 session 表与设备表（10k 请求级别会放大为写热点）。
- 超时后 `flush()` 并 302 到 `LOGIN_URL?next=...`，同时写审计日志
  `session_idle_timeout`（只含角色与 IP）。

### 2.4 页面只暴露非敏感字段

`/account/sessions/` 展示：设备标识前 8 位、来源 IP、截断到 200 字符的 UA、
最近活动时间、是否当前设备。**不展示**服务端 Session Key、完整 UA 原文之外的信息。

## 3. 运维配置

```dotenv
# 默认关闭；确认各端接受"无操作自动退出"后再开启
DJANGO_SESSION_IDLE_ENABLED=True
DJANGO_SESSION_IDLE_MINUTES=30
```

开启前建议先确认：

1. 各角色页面是否有长时间停留但无请求的场景（如大屏、打印预览）；
2. 反向代理的空闲超时是否短于本值（否则先被代理断开）；
3. 页面表单是否有未提交的草稿（超时会 flush 会话，草稿需前端本地保存）。

## 4. 迁移与数据影响

`0006_login_device` 只新增表 `app01_login_device`，不改动既有表结构。

- 正式库 `smass` 本轮**未执行**该迁移（只读策略），上线前需由授权发布流程执行；
- 未迁移时 `register_device` 抛错会被 `establish_session` 捕获并记
  `session_device_register_failed` 警告，**不阻断登录**，这是有意的降级设计；
- 该表不含密码、令牌或身份证号，只有设备标识、账号字符串、角色、IP、UA 与时间。

## 5. 已知边界

1. R21/R22 隔离配置使用 `request.user` 与统一账号体系，不写 `session['info']`，
   因此 S17 中间件在这些配置下不生效（`session['info']` 缺失即跳过）。
   设备表本身与身份来源解耦，后续接入统一账号时可直接复用。
2. 设备列表按"当前账号当前角色"过滤；同一自然人跨角色（教师 + 管理员）
   会显示为两个账号下的两条独立设备列表，这是既有三表身份模型的边界，
   R22 统一身份切换后可按 `Account` 聚合。
3. 空闲超时不处理"浏览器后台标签页"场景：只要页面持续发出请求就不算空闲。

## 6. 测试命令

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test app01.tests.test_s17_session_security
& $py manage.py test app01.tests.test_auth app01.tests.test_authorization
& $py manage.py test r21_account --settings=smass.settings_r21
& $py manage.py test r22_account --settings=smass.settings_r22
```

实测结果（2026-10-30）：

| 套件 | 结果 |
|---|---|
| `app01.tests.test_s17_session_security` | 19 例 OK |
| `app01.tests.test_auth` + `test_authorization` | 38 例 OK |
| `r21_account`（`settings_r21`） | 110 例 OK |
| `r22_account`（`settings_r22`） | 117 例 OK |
