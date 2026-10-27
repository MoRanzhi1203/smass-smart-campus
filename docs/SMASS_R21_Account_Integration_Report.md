# SMASS R2.1 统一账号集成报告（Account Integration Report）

- 隔离库：`smass_r21_proto`（7 张 `r21_*` 表）
- 配置：`smass/settings_r21.py`（正式 `settings.py` **不含** `r21_account`）
- 正式 `smass` 库：**账号读写路径未切换（NOT DONE / REQUIRES EXPLICIT AUTHORIZATION）**

## 1. 模型（最小可行）

| 模型 | 作用 | 关键约束 |
|---|---|---|
| `Account(AbstractBaseUser, PermissionsMixin)` | 唯一认证主体 | `login_name` 唯一；`must_change_password`、`is_active`、`scope_college`、停用审计字段 |
| `AccountRole` | 角色授予记录（含撤销） | 条件唯一 `(account, role)` where `revoked_at IS NULL` |
| `LegacyAccountLink` | 旧表 → Account 唯一映射 | 唯一 `(source_table, source_pk)`；OneToOne Account |
| `StudentProfile` / `TeacherProfile` | 业务档案 | `student_no` / `teacher_no` 唯一 |
| `AccountAuditLog` | 账号域审计 | action/actor/target/ip |
| `LoginAttempt` | 持久化限速 | 双维度索引 |

设计要点：
- `AbstractBaseUser` 是**必要条件**（`get_session_auth_hash` 等契约），实测见架构决策文档；
- 覆盖 `groups` / `user_permissions` 的 `related_name='r21_accounts'`，否则与 `auth.User` 报 `fields.E304`；
- `App01` 旧表**一行未改**。

## 2. 回填（P2）

命令：`manage.py backfill_accounts_r21 --settings=smass.settings_r21`

| 特性 | 实测 |
|---|---|
| `--dry-run` | 只统计：`processed=6 created=6` |
| 实跑 | `accounts=6 roles=6 links=6 student_profile=3 teacher_profile=2` |
| 幂等 | 二次执行 `created=0 skipped=6` |
| 哈希原样 | 直接 `account.password = row.password`，**不调用** `set_password` |
| 撞号 | 记录 conflict、跳过、不覆盖 |
| 库校验 | 非 `smass_r21_*` 直接 `CommandError` |

一致性校验：`verify_account_consistency --strict-count` → **PASS**（映射覆盖 / 哈希一致 / 角色匹配 / 启用状态自洽）。

## 3. 双写（P3）

`r21_account/dual_write.py`，覆盖：`create_student` / `create_teacher` / `change_password` / `deactivate` / `activate`。

| 特性 | 实现 |
|---|---|
| 唯一写入权威 | **服务层**（不用 signal） |
| 原子性 | 每个动作一个 `transaction.atomic()`，任一侧失败整体回滚 |
| 哈希同源 | `make_password` 一次，两表赋同一字符串 |
| 审计 | 每次写 `AccountAuditLog` |

故障注入实测（`test_dual_write.FaultInjectionTests`）：
- 新表 `Account.save` 抛错 → **旧表也已回滚**；
- `StudentProfile.create` 抛错 → 两表均回滚。

## 4. 明确未做

| 项 | 状态 |
|---|---|
| 正式库回填 | **NOT DONE**（只在 `smass_r21_proto`） |
| 正式读取切换（P4） | **NOT DONE** |
| 旧表删除 | **未做**（保留至可证明回滚且独立评审） |
| `AUTH_USER_MODEL` 修改 | **未做** |
