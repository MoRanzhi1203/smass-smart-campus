# SMASS R2.2 兼容性审计（G1 Compatibility Audit）

- 对象：`r21_account/backends.py::AccountBackend` 与 Django 认证体系
- 方法：真实集成测试（Django test Client + 真实 ORM），不使用 mock 替代
- 测试文件：`r21_account/tests/test_django_compat.py`（**12 例，12/12 PASS**）

## 1. 审计矩阵

| # | 兼容点 | 假设 | 实测结果 | 状态 |
|---|---|---|---|---|
| 1 | `has_module_perms` | ModelBackend 继承方法可用 | 可用 | PASS |
| 2 | `get_all_permissions` | 返回 `app.codename` 集合 | 含 `r21_account.view_data` | PASS |
| 3 | `get_group_permissions` | Account.groups 生效 | 含 `r21_teacher` | PASS |
| 4 | `get_user_model()` | 仍是 `auth.User` | `auth.User` | PASS（同时也是**限制**） |
| 5 | `Account` 与默认用户模型不同 | 两者 label 不同 | 不同 | PASS |
| 6 | `AuthenticationForm` | 可用 Account 认证 | `form.get_user()` 为 `Account` | PASS |
| 7 | 错误密码 | 表单拒绝 | 拒绝 | PASS |
| 8 | **`django_admin_log` 外键** | 以 Account.pk 写日志会失败 | 抛 `IntegrityError` | **FAIL（设计限制，非缺陷）** |
| 9 | auth.User 与 Account 权限隔离 | 互不串用 | 隔离 | PASS |
| 10 | Group 不串用 | `r21_teacher` 不挂到 auth.User | 不串 | PASS |
| 11 | Permission 共享表 | 同一 ContentType 绑定 Account | 一致 | PASS |
| 12 | 空 auth_user 时写日志 | 必失败（证明 FK 指向 auth_user） | `IntegrityError` | PASS（证明） |

## 2. 关键发现（路径 A 的真实边界）

### 2.1 `django_admin_log.user_id` 外键指向 `auth_user`

实测（第 8/12 项）：

```
IntegrityError: Cannot add or update a child row:
a foreign key constraint fails (`django_admin_log`, CONSTRAINT ... FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`))
```

含义：
- Django admin 每次增删改会写 `LogEntry(user_id=request.user.pk)`；
- 若 `request.user` 是 `Account`，其 pk 去校验 `auth_user(id)`；
- **后果 A**：`auth_user` 无该 id → 500（IntegrityError）；
- **后果 B（更危险）**：`auth_user` 恰好有同 id 行（两表都是自增 int）→ 日志**记到错误的人名下**。

这不是"配置问题"，而是路径 A 必须显式处理的**结构性限制**。

### 2.2 `get_user_model()` 仍返回 `auth.User`

所有按 `AUTH_USER_MODEL` 取用户模型的 Django 组件（`django.contrib.auth.forms`、
`django.contrib.admin`、部分第三方包）仍会拿到 `auth.User`，而不是 `Account`。
因此路径 A 下**不能**直接依赖这些组件的用户语义。

### 2.3 已确认可用的能力

`has_perm` / `has_module_perms` / `get_all_permissions` / `get_group_permissions` /
`AuthenticationForm` / `login` / `logout` / `get_session_auth_hash` / `force_login`
均对 `Account` 成立。权限与 Group 在 `auth.User` 与 `Account` 之间不串用。

## 3. 结论

| 判断 | 说明 |
|---|---|
| AccountBackend 主体可用 | 是（认证、会话、权限判定） |
| 与 Django **admin log** 不兼容 | 是（FK 指向 auth_user） |
| 与依赖 `AUTH_USER_MODEL` 的组件不兼容 | 是（`get_user_model()` 仍是 auth.User） |
| 是否"整体兼容" | **否** —— 单项测试通过不能推出整体兼容 |

> 这正是计划要求的："不得因为单项测试通过就自动推断整个架构兼容。"
