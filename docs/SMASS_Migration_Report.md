# SMASS 迁移报告（Migration Report）

- 执行时间：2026-10-27
- 目标库：`smass` @ `localhost:3306`（MySQL 8.0.18）
- 结论：**迁移已在确认为空的本地开发库上完整执行，26 张表，迁移全部应用，种子数据幂等可复跑**

## 1. 迁移前状态（只读核验）

| 检查项 | 结果 |
|---|---|
| 库是否存在 | 是（`smass`） |
| 表数量 | **0** |
| 库默认字符集 | `utf8` / `utf8_general_ci` |
| `showmigrations app01` | `0001_initial` `0002_rename_studentsunion_leaguecadres` `0003_classcommittee` 全部为 `[ ]` |
| `manage.py check` | 0 issues |
| `makemigrations --check --dry-run` | No changes detected（模型与既有迁移一致） |
| `migrate --plan` | 内置 `contenttypes/auth/admin/sessions` + `app01` 三项待应用 |
| 同实例其他库 | 存在 20+ 个无关业务库（`school`、`ruoyi` 等），**未触碰** |

## 2. 数据库可写门禁判定

| 门禁条件 | 状态 | 证据 |
|---|---|---|
| 是本机隔离实例 | ✅ | `localhost:3306`，开发机本地 MySQL |
| 无真实业务数据 | ✅ | 0 张表 |
| 有可恢复备份 | ✅ | `E:\PythonWeb\_smass_backups\smass_src_20261027_014612.zip`（9.1 MB） |
| 有版本恢复点 | ✅ | Git 基线 `4bddb70` |
| 迁移已审查 | ✅ | 0001-0003 为存量迁移；新增 0004 仅 `AlterField` 扩长度 |
| 未使用未授权凭据 | ✅ | 使用项目既有本地配置，未新增/外泄凭据 |

**判定：`WRITABLE`** —— 允许执行 `migrate` 与幂等种子命令。

**仍然禁止**（本轮未执行，也未计划执行）：`flush`、`drop database`、`migrate zero`、清空业务表、修改他人数据库。

## 3. 迁移执行

```
Applying contenttypes.0001_initial ... OK
Applying auth.0001_initial ... OK
Applying admin.0001_initial ... OK
Applying admin.0002_logentry_remove_auto_add ... OK
Applying admin.0003_logentry_add_action_flag_choices ... OK
Applying app01.0001_initial ... OK
Applying app01.0002_rename_studentsunion_leaguecadres ... OK
Applying app01.0003_classcommittee ... OK
Applying app01.0004_alter_admin_password_alter_student_password_and_more ... OK
Applying contenttypes.0002_remove_content_type_name ... OK
Applying auth.0002 ... auth.0012 ... OK
Applying sessions.0001_initial ... OK
```

退出码 `0`。

### 3.1 新增迁移 0004 内容审查

```python
operations = [
    migrations.AlterField(model_name="admin",   name="password", field=CharField(max_length=128)),
    migrations.AlterField(model_name="student", name="password", field=CharField(max_length=128)),
    migrations.AlterField(model_name="teacher", name="password", field=CharField(max_length=128)),
]
```

- 纯 `AlterField` 扩长度：MySQL 侧为 `varchar(64) → varchar(128)`，**不丢数据、不重建语义**。
- 动机：Django PBKDF2 哈希约 88-90 字符，64 位会截断。

## 4. 迁移后状态

`showmigrations app01`：

```
[X] 0001_initial
[X] 0002_rename_studentsunion_leaguecadres
[X] 0003_classcommittee
[X] 0004_alter_admin_password_alter_student_password_and_more
```

**表清单（26 张）**

| 分类 | 表 |
|---|---|
| 业务（16） | `app01_admin`、`app01_student`、`app01_teacher`、`app01_college`、`app01_major`、`app01_classes`、`app01_grade`、`app01_department`、`app01_leaguecadres`、`app01_classcommittee`、`app01_position`、`app01_teacherposition`、`app01_nation`、`app01_building`、`app01_dormitory`、`app01_dormitorynumber` |
| Django 内置（10） | `auth_user`、`auth_group`、`auth_permission`、`auth_user_groups`、`auth_user_user_permissions`、`auth_group_permissions`、`django_content_type`、`django_admin_log`、`django_session`、`django_migrations` |

## 5. 种子数据（`seed_dev`）

### 5.1 首次执行

```
seed_dev 完成：新建 26 项，复用 0 项
```

### 5.2 幂等验证（立即二次执行）

```
seed_dev 完成：新建 0 项，复用 26 项
本次没有新建任何记录（已全部存在），说明命令是幂等的。
```

### 5.3 当前行数

| 模型 | 行数 |
|---|---|
| `College` | 2 |
| `Grade` | 3 |
| `Major` | 3 |
| `Classes` | 2 |
| `Position` | 4 |
| `Teacher` | 2 |
| `TeacherPosition` | 2 |
| `Admin` | 1 |
| `Student` | 3 |
| `Department` | 2 |
| `LeagueCadres` | 1 |
| `ClassCommittee` | 1 |
| `Nation` / `Building` / `Dormitory` / `DormitoryNumber` | 0（未使用） |

> 种子账号的随机初始密码只在命令标准输出中出现一次，**未写入本报告、未写入日志文件**。

## 6. 隔离测试库验证

- 每次 `manage.py test app01` 都会在 MySQL 上创建 `test_smass`、执行全部迁移、跑完 79 个用例后销毁。
- 从零建库 → 迁移 → 测试 → 销毁 的完整链路已多轮通过，证明"迁移可重复、可从零重建"。

## 7. 已知遗留：库/表字符集

| 项 | 现状 | 风险 | 建议 |
|---|---|---|---|
| 库 | `utf8` / `utf8_general_ci` | 不支持 4 字节字符（emoji） | R2 迁移到 `utf8mb4` / `utf8mb4_general_ci` |
| 表 | 全部 `utf8_general_ci`（继承库默认） | 同上；`utf8_general_ci` 对某些生僻字排序不精确 | 同上，需 `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4` |

**本轮未执行**字符集转换：它属于"改变既有数据结构"的中风险操作，且当前无 4 字节字符需求。
迁移步骤（供后续执行）：

```sql
ALTER DATABASE smass CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
-- 逐表执行（建议在业务低峰、并先备份）
ALTER TABLE app01_student CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

Django 连接层已固定 `charset=utf8mb4`（`settings.DATABASES.OPTIONS`），新建表会继承该连接字符集。

## 8. 回滚方案

| 层 | 回滚方式 |
|---|---|
| 源码 | `git reset --hard 4bddb70`（或解压 `_smass_backups\smass_src_20261027_014612.zip`） |
| 迁移 | `python manage.py migrate app01 0003`（仅回滚密码长度，数据保留）；若需回到零表：`migrate app01 zero`（**会删业务表，需明确授权**） |
| 数据 | 本轮为"从 0 建表 + 种子"，无历史业务数据可丢；种子可用 `seed_dev` 重建 |

## 9. 结论

- 数据库从"0 表"变为"26 表 + 4 个业务迁移全部应用"，迁移链路真实、可重复、有隔离库验证。
- 种子命令幂等（第二次 0 新建）。
- 唯一遗留为字符集（`utf8`），不影响功能，已在 R2 与安全报告中列为跟进项。
