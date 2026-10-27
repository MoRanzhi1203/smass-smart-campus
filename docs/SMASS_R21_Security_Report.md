# SMASS R2.1 安全报告（Security Report）

## 1. 认证

| 控制点 | 状态 |
|---|---|
| 密码哈希 | Django PBKDF2（`set_password`/`check_password`） |
| 会话哈希 | `get_session_auth_hash` 生效，改密后旧会话失效（测试） |
| 账号枚举 | 登录失败统一提示；不区分"账号不存在"与"密码错误" |
| 停用账号 | `ModelBackend.user_can_authenticate` 拒绝（测试） |
| 会话固定 | Django `login()` 内部 `cycle_key()` |
| 开放重定向 | R2.1 登录固定跳 `/r21/home/`，无 `next` 参数 → **不存在该攻击面** |
| 认证主体 | `Account`（`AUTH_USER_MODEL` **仍是** `auth.User`，正式路径未切换） |

## 2. 授权

| 控制点 | 状态 |
|---|---|
| 权限载体 | Django `Group`/`Permission`（`r21_*`），非自造判定 |
| 默认拒绝 | 无角色 → `none()`；scope 缺失 → `none()`（测试） |
| 高危权限 | `dangerous_bulk_delete` **不授予任何角色**（测试锁定） |
| 角色撤销 | 即时失效（权限 + 可见范围，测试） |
| 伪造入参 | 会话身份不随客户端参数变化（测试） |
| 对象级范围 | `scoping.py` 按角色收窄查询集 |

## 3. 密码生命周期

| 控制点 | 状态 |
|---|---|
| 强制改密 | 三端统一中间件；页面 302 / AJAX 403；白名单路径受控 |
| 临时口令 | `set_temporary_password` 置 `must_change_password=True`，明文不落日志 |
| 强度校验 | `validate_password`（长度/常见/纯数字） |
| 长度上限 | 已取消 6-10 位上限，20 位强密码通过 |
| 改密后会话 | `update_session_auth_hash`，当前会话保留、他处失效 |

## 4. 持久化限速

| 控制点 | 状态 |
|---|---|
| 跨会话 | 数据库记录，新 client 仍被锁（测试） |
| 防误锁 | `(login_name, ip)` 为主维度；账号级阈值更高（20） |
| 时间边界 | 15 分钟窗口 + 900 秒锁定，滑动过期 |
| 清理 | 成功登录后清理该账号失败记录 |

## 5. 数据与日志

| 控制点 | 状态 |
|---|---|
| 哈希泄露 | 一致性校验/审计均不含哈希；`AccountAuditLog` 只记 action/target |
| 密码明文 | 仅临时口令一次性展示；未写入日志/报告 |
| 审计覆盖 | create / backfill / login / login_failed / password_change / password_reset / role_grant / role_revoke / deactivate / must_change / dangerous_blocked |
| 旧表哈希 | **原样搬迁**，未二次加密；`verify_account_consistency` 逐条比对 |

## 6. 边界与未做

| 项 | 状态 |
|---|---|
| 正式库认证切换 | **NOT DONE / REQUIRES EXPLICIT AUTHORIZATION** |
| `AUTH_USER_MODEL` 修改 | **未做** |
| 旧表/原型库删除 | **未做**（计划禁止） |
| 远程推送 | 未做 |
| 密码历史复用限制 | 未做 |
| 分布式限速共享存储 | 未做（表结构已支持） |
| 依赖漏洞 | 0（`pip-audit` 实测，R1.5 已修复 87 个） |
