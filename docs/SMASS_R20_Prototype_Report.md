# SMASS R2.0 原型报告（Prototype Report）

- 原型库：`smass_proto_account`（**隔离库**，与 `smass` 分离）
- 加载方式：`smass/settings_proto.py`（正式 `settings.py` **不包含** `proto_account`）
- 结论：隔离原型与迁移演练 **PASS**；**正式账号切换 = NOT DONE**

## 1. 隔离模型（P1）

`proto_account/models.py`，5 个模型：

| 模型 | 关键字段 |
|---|---|
| `Account` | `login_name`(唯一)、`password`、`display_name`、`person_type`、`is_active`、`must_change_password`、`password_changed_at`、`last_login_at`、`failed_attempts`、`locked_until`、`legacy_source`、`legacy_pk` |
| `AccountRole` | `account`、`role`、`granted_at`；唯一约束 `(account, role)` |
| `StudentProfile` | `student_no`(唯一)、姓名/性别/民族/身份证/手机/QQ/地址/班级名/政治面貌 |
| `TeacherProfile` | `teacher_no`(唯一)、…、入职时间、院系名 |
| — | `Account` 唯一约束 `(legacy_source, legacy_pk)`，保证回填可追溯且幂等 |

设计取舍：
- `classes`/`college` 在 Profile 中暂存**名称字符串**而非外键，避免原型阶段引入跨 app 迁移依赖；
- `must_change_password` 默认 `True`（新账号首次登录必须改密）；
- 限速字段（`failed_attempts`/`locked_until`）为 R2.1 持久化限速预留。

## 2. P0：隔离库全新迁移

```
CREATE DATABASE smass_proto_account   -- utf8/utf8_general_ci
makemigrations proto_account --settings=smass.settings_proto
  → proto_account/migrations/0001_initial.py（4 个 CreateModel）
migrate --settings=smass.settings_proto --noinput
  → auth.* / admin.* / contenttypes.* / app01.* / proto_account.0001_initial / sessions 全部 OK
```

结果：原型库拥有与 `smass` 同构的 `app01` 表 + 4 张新账号表，互不干扰。

## 3. 数据搬运（避免跨库写入）

用 Django 官方工具而非自写 SQL：

```powershell
manage.py dumpdata app01 --indent 2 -o legacy.json --settings=smass.settings
manage.py loaddata legacy.json --settings=smass.settings_proto
# → Installed 26 object(s)
```

好处：**密码哈希原样导出导入**，不经任何再加密。

## 4. 回填（P2）

命令：`proto_account/management/commands/backfill_accounts.py`

| 特性 | 实现 |
|---|---|
| 幂等 | 以 `(legacy_source, legacy_pk)` 判重 |
| 干跑 | `--dry-run` 只统计 |
| 断点续跑 | `--since N` 按 pk 跳过 |
| 分批事务 | `--batch-size`（默认 200，每行一个事务以保证单行隔离） |
| 冲突处理 | `login_name` 被其他来源占用 → 记 conflict 并跳过，**不覆盖** |
| 回滚 | `--rollback` 删除所有 `legacy_source` 非空的行（级联 Profile/Role） |
| 密码 | **直接赋值旧哈希**，绝不调用 `make_password` |
| 库校验 | 连接库名必须以 `smass_proto_` 开头，否则 `CommandError` |

### 4.1 实测

```
[1] dry-run   : processed=6 created=6 skipped=0 conflicts=0 errors=0
[2] real run  : processed=6 created=6 skipped=0 conflicts=0 errors=0
    accounts total=6  account_roles=6  student_profile=3  teacher_profile=2
[3] re-run    : processed=6 created=0 skipped=6   ← 幂等成立
```

## 5. 一致性校验

`scripts/proto_verify.py`（只读）：

```
legacy accounts : 6
proto accounts  : 6
account roles   : 6
student profile : 3
teacher profile : 2
cross-type login collisions in legacy data: 0

[PASS] 账号数量 / 密码原样迁移 / 角色映射 / 档案数量 / login_name 唯一性 全部一致
```

其中**密码原样性**逐行比对 `Account.password` 与来源表 `password`，任何不一致都会 FAIL
（这是 R1 曾踩过的"二次加密"坑的专用守卫）。

## 6. 失败注入（P4）

`scripts/proto_failure_injection.py`，实测 **9/9 PASS**：

| # | 场景 | 期望 | 结果 |
|---|---|---|---|
| 1 | 基线回填 | accounts == legacy rows | PASS（6） |
| 2 | 重复 `(account, role)` | `IntegrityError` | PASS |
| 3 | 跨类型撞号（占位账号占住某学号） | 记 conflict、不覆盖 | PASS（conflicts=1，占位密码未被改写） |
| 4 | 清理占位后重新回填 | 补全到 6 | PASS |
| 5 | 回滚 | 删除全部回填行 | PASS（deleted=17，含级联） |
| 6 | 回滚不影响旧表 | 旧表仍 6 行 | PASS |
| 7 | 断点续跑（`--since 0..5`） | 最终 6 条 | PASS |
| 8 | 重复执行 | 0 新增 | PASS |
| 9 | 收尾恢复 | 6 条 | PASS |

第 2 项同时证明"角色提升/重复授予"在数据层被唯一约束挡住。

## 7. 原型库当前状态

| 表 | 行数 |
|---|---|
| `proto_account_account` | 6 |
| `proto_account_accountrole` | 6 |
| `proto_account_studentprofile` | 3 |
| `proto_account_teacherprofile` | 2 |

> 原型库**独立存在**，不影响 `smass`；如需清理，`DROP DATABASE smass_proto_account` 即可
> （该库名命中白名单前缀，属受控对象）。

## 8. 正式切换前置清单（P5）

**必须先全部满足，才能讨论切换**：

| # | 条件 | 当前状态 |
|---|---|---|
| 1 | ADR 经评审确认路径 A | 建议已出，**未评审** |
| 2 | 双写（P3）实现并有一致性校验任务 | **未实现** |
| 3 | 认证后端 + `request.user` 适配 | **未实现** |
| 4 | 三端强制改密 UI（`must_change_password` 落地） | **未实现** |
| 5 | 持久化限速接入 | **未实现** |
| 6 | RBAC codename 与角色-权限矩阵 | **未实现** |
| 7 | 全量回归（app01 112 + E2E 16）在切换分支通过 | 未在切换分支验证 |
| 8 | 生产前全库备份 + 恢复演练 | 演练已通过（`smass`），切换前需再做一次 |
| 9 | 旧表保留期限与清理责任人 | **未定** |
| 10 | 回滚演练（切回旧路径） | **未做** |

## 9. 阻断与结论

| 项 | 结论 |
|---|---|
| 隔离原型 | PASS（模型、迁移、回填、校验、失败注入） |
| 数据校验可重复 | PASS（`proto_verify.py` / `proto_failure_injection.py` 可复跑） |
| 回滚演练 | PASS（`--rollback` 实测） |
| ADR | 已产出，**建议路径 A** |
| **正式账号切换** | **NOT DONE** —— 明确列为受控后续任务，需另行授权 |
| `AUTH_USER_MODEL` | **未修改**，`smass` 库**未新增任何列** |
