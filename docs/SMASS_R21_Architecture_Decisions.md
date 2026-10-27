# SMASS R2.1 架构决策（Architecture Decisions）

- 状态：四项决策均已**用代码实验核对**，非纸面结论
- 实验库：`smass_r21_proto`（隔离）
- 实证测试：`r21_account/tests/test_auth_integration.py`（13 例，**13/13 PASS**）

## 决策 1：统一认证与 Django 集成 —— 采用「标准契约 + 自定义 Backend」

### 1.1 计划提出的疑问

> 不要假设设置自定义 `AUTHENTICATION_BACKENDS` 后 `request.user` 天然成为非
> `AUTH_USER_MODEL` 的 Account。

### 1.2 实测结论：**可行，但有两个必要条件**（都不是"天然"的）

| 必要条件 | 若缺失的后果 | 证据 |
|---|---|---|
| `Account` 必须继承 `AbstractBaseUser`（或自行实现 `get_session_auth_hash`/`set_password`/`check_password`） | `login()` 无法写入有效 session hash；改密后旧会话不会被拒绝 | `test_password_change_invalidates_old_session` PASS |
| 必须覆盖 `PermissionsMixin.groups` / `user_permissions` 的 `related_name` | 与默认 `auth.User` 反向访问器冲突：`fields.E304 Reverse accessor 'Group.user_set' clashes` | 首次 `makemigrations` **实际报错**，改 `related_name='r21_accounts'` 后通过 |

### 1.3 采用方案

- 保留 Django 原生 `login()` / `logout()` / `AuthenticationMiddleware`，**不 hack `request.user`**；
- `AccountBackend(ModelBackend)` 负责 `authenticate` 与 `get_user`；
- 实测（`test_request_user_is_account_instance`）：真实 HTTP 请求下
  `resp.wsgi_request.user` 的类型**就是 `Account`**，且 `pk` 正确；
- `session[SESSION_KEY]` = Account 主键，`session[BACKEND_SESSION_KEY]` = `r21_account.backends.AccountBackend`。

### 1.4 与 `auth_user` 的关系（明确）

- `auth_user` 表**仍然存在**（`django.contrib.auth` 未移除），因为 `django_admin_log`、
  `auth_permission`、`Group` 都依赖它；
- 但 **登录主体是 `Account`**，`auth_user` 在本原型中**不参与认证**；
- 两套身份不会互相矛盾，因为 R2.1 的 `settings_r21` **移除了**
  `app01.middleware.auth.AuthMiddleware`（它依赖 `session['info']` 的旧三表身份），
  环境中只认 `request.user`。

### 1.5 正式库不改

- `AUTH_USER_MODEL` **未修改**（仍是 `auth.User`）；
- `smass` 库的认证读写路径**未切换**；
- 本决策只证明"技术上可行 + 前置条件是什么"，不构成切换授权。

## 决策 2：权限能力 —— `PermissionsMixin` + Django `Group`/`Permission` 桥接

| 选项 | 结论 |
|---|---|
| 迁就 Django `Group`/`Permission` | **采用** |
| 独立 Role/Permission 表 | 仅 `AccountRole` 作为**授予记录与审计**，权限判定仍走 Django |

实现：
- `r21_account.ensure_role_groups()` 幂等创建 4 个 Group（`r21_system_admin` /
  `r21_college_admin` / `r21_teacher` / `r21_student`），并为每个 Group 设置
  `Permission`；
- `AccountRole` 授予/撤销时在同一事务内 `sync_account_groups()`，把活跃角色映射为
  Group 成员关系；
- 权限 codename 绑定到 `r21_account.Account` 的 `ContentType`，检查形式
  `request.user.has_perm('r21_account.<codename>')`。

权限矩阵（`r21_account/permissions.py`）：

| 角色 | view | add | change | delete | reset_password | import_data | manage_roles | dangerous_bulk_delete |
|---|---|---|---|---|---|---|---|---|
| system_admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **❌（默认无人）** |
| college_admin | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| teacher | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| student | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

实测证据：
- `test_permission_before_grant` / `test_permission_after_grant` PASS；
- `test_dangerous_permission_granted_to_nobody` PASS（系统管理员也没有该权限）；
- `test_revoke_role_removes_permission` PASS（撤销后立刻失效）。

对象级范围：`Account.scope_college` + 查询集过滤（`SCOPE_RULES` 记录语义），
在 G3 的 RBAC 测试中验证（不在本决策文件里空谈）。

## 决策 3：多角色 / 多账号 —— 不自动合并，保留唯一映射

| 规则 | 实现 |
|---|---|
| 同一人有多号（教师号 + 管理员号） | **默认不合并**，各自一个 `Account` |
| 可追溯 | `LegacyAccountLink(source_table, source_pk)` 唯一约束，OneToOne 到 Account |
| 角色 | `AccountRole` 多对多（同一 Account 可多角色），撤销保留历史 |
| 登录入口 `role_hint` | **只作入口选择，不作权限来源**；权限只看 `AccountRole` → Group |
| 撞号 | 回填时若 `login_name` 已被其他来源占用 → 记录冲突、**跳过、不覆盖**，输出不含敏感数据的清单 |

## 决策 4：密码与旧表生命周期

| 项 | 决策 |
|---|---|
| 三端密码策略 | 统一走 Django `validate_password`（`password_policy_errors()`） |
| 学生端 6–10 位上限 | **取消上限**（R2.1 原型已无上限）；下限沿用 `MinimumLengthValidator(min_length=6)` |
| 旧密码验证兼容 | `Account.set_password/check_password` 为标准 PBKDF2；旧 `app01` 表的 MD5 兼容**保持原样不动**，回填时哈希**原样搬迁** |
| `must_change_password` | 新账号/临时口令默认 `True`，强制改密后才置 `False` |
| 旧表生命周期 | **至少保留至可证明回滚并独立评审**；本轮**不删除**任何旧表、不删除任何原型库 |

## 不实施项（明确）

| 项 | 原因 |
|---|---|
| 正式 `AUTH_USER_MODEL` 切换 | 需单独授权；ADR（R2.0）判定中途切换风险高 |
| 删除 `app01.Admin/Student/Teacher` | 计划禁止自动删除；旧表仍是唯一权威 |
| 删除 `smass_proto_account` / `smass_proto_user_model` | 计划明确禁止 |
| 在 `smass` 上执行账号读写切换 | 计划明确要求 NOT DONE |
| 重写既有迁移 | 禁止 |
| 推送远程 | 禁止 |

## 迁移依赖图（R2.1 原型）

```
auth.0001_initial
  └── auth.0012 (migrations)
        └── r21_account.0001_initial   ← 依赖 auth（Group/Permission）
              ├── Account
              ├── AccountRole
              ├── LegacyAccountLink
              ├── StudentProfile
              ├── TeacherProfile
              ├── AccountAuditLog
              └── LoginAttempt
app01.0001-0004  ──（只读引用，不新增依赖）
```

`r21_account` 的迁移**不依赖** `app01` 的迁移（回填通过运行时 ORM 读取旧表），
因此原型可以独立推进，也不会污染 `app01` 的迁移链。

## 风险矩阵

| 风险 | 影响 | 缓解 |
|---|---|---|
| 两套用户模型共存导致 `related_name` 冲突 | 迁移失败 | 已覆盖字段并显式命名（实测修复） |
| `app01` 中间件与统一认证矛盾 | 授权判定混乱 | `settings_r21` 移除旧中间件，环境只认 `request.user` |
| 回填覆盖已有账号 | 数据损坏 | 冲突检测 + 跳过 + 不覆盖（G2 实现） |
| 双写半成功 | 数据不一致 | 单事务 + 一致性校验命令 + 故障注入测试（G2） |
| 限速被恶意用于锁定他人 | 可用性攻击 | 按 `(login_name, ip)` 组合计数，账号维度阈值更高（G4） |

## 回滚限制

| 变更 | 回滚方式 | 限制 |
|---|---|---|
| `r21_account` 表 | `migrate r21_account zero`（仅原型库） | 影响原型数据，不影响 `smass` |
| 角色/权限 | 撤销 `AccountRole` + Group 解绑 | 已保留历史记录 |
| 回填 | 删除 `LegacyAccountLink` 级联删除 Account | 需先确认无新增数据 |
| 正式切换 | 不适用（未发生） | — |
