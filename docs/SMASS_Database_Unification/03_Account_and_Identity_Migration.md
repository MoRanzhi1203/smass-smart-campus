# 03 账号与身份迁移

> 源：`smass.app01_admin/student/teacher`（只读）
> 目标：`r21_account.Account` + `AccountRole` + `StudentProfile` / `TeacherProfile`
> 演练库：`smass_unified_verify`
> 脚本：`scripts/legacy_migration.py --settings=smass.settings_unified_verify`

---

## 1. 映射规则

| 源表 | 源主键 | 登录名 | 人员类型 | 角色 | 业务档案 |
|---|---|---|---|---|---|
| `app01_student` | 学号（10 位） | 学号 | `student` | `student` | `StudentProfile` + `StudentRecord` |
| `app01_teacher` | 工号（7 位） | 工号 | `teacher` | `teacher` | `TeacherProfile` + 学院 `Membership` |
| `app01_admin` | 管理员编号（3 位） | 编号 | `admin` | `system_admin` | — |

| 项 | 处理 |
|---|---|
| 唯一锚点 | `LegacyAccountLink(source_table, source_pk)`，幂等 |
| 已存在账号 | 复用（`merged` 计数），补建 link 与角色 |
| 登录名冲突 | 当前源数据无冲突；若冲突，保留原账号并记录为 `UNRESOLVED`，不覆盖 |
| 密码 | 源为 `pbkdf2_sha256$` → 直接继承；非 PBKDF2 → `set_unusable_password()` + `must_change_password=True` |
| 首次改密 | 迁移账号 `must_change_password=False`（密码可用），由密码策略另行要求 |
| 停用 | 源无停用字段，默认 `is_active=True` |

---

## 2. 实测结果

| 指标 | 数值 | 证据 |
|---|---|---|
| 迁移学生账号 | 3 | `migration_apply.json` |
| 迁移教师账号 | 2 | 同上 |
| 迁移管理员账号 | 1 | 同上 |
| 新建账号 | 6 | `created_accounts=6` |
| 合并/复用账号 | 0 | `stats.merged=0` |
| 拒绝 | 0 | `stats.rejected=0` |
| 未解决 | 0 | `stats.unresolved=0` |
| 密码可继承（PBKDF2） | 学生 3/3、教师 2/2 | 源表 `password LIKE 'pbkdf2%'` |
| PII 掩码 | 手机号 5 条 | `stats.transformed=5` |

角色与权限验证（`migration_verify.json`）：

| 用例 | 期望 | 实测 |
|---|---|---|
| 迁移学生访问 `/admin/` | 403 | 403 |
| 迁移学生访问 `/student/` | 200 | 200 |
| 迁移教师访问 `/admin/` | 403 | 403 |
| 迁移管理员访问 `/admin/` | 200 | 200 |
| 每个学生有 `student` 角色 + 学籍 | 是 | 是 |
| 每个教师有 `teacher` 角色 + 档案 | 是 | 是 |
| 每个管理员有 `system_admin` | 是 | 是 |

---

## 3. 密码与登录兼容

- 继承的是哈希本身，不重置密码；迁移后可**用原密码登录**（受原密码策略约束）。
- 若源为历史 MD5/明文，迁移设不可用密码，必须由管理员重置（管理端"重置口令"）。
- 产品登录限速、会话世代、强制改密中间件对新旧账号一致。
- 迁移不改 `AUTH_USER_MODEL`；`auth.User` 仍为空置。

---

## 4. 敏感信息保护

| 字段 | 策略 | 实测 |
|---|---|---|
| 手机号 | 掩码（前 3 + `****` + 后 4） | 5 条已掩码 |
| 身份证 | **不迁移** | `card_id` 全部为空 |
| QQ / 地址 / 拼音 | 不迁移 | — |
| 密码哈希 | 继承（不可逆） | 可登录 |
| 真实 PII 开启 | 需 `SMASS_MIGRATE_REAL_PII=YES_I_HAVE_AUTHORIZATION` | 本轮未开启 |

---

## 5. 审计与会话

- 迁移写 `LegacyAccountLink`（锚点）与 `AccountRole`（授予人 `legacy-migration`）。
- 不迁移 `django_session`（会话不可复用）。
- 迁移账号的审计追溯：`LegacyAccountLink` 提供"新旧对应"，
  但历史操作日志不迁移（源库无对应日志表）。

---

## 6. 冲突与未解决

| 场景 | 本轮状态 | 处理 |
|---|---|---|
| 登录名重复 | 未发生 | 若发生：不覆盖，记录 UNRESOLVED，人工处理 |
| 一人多身份（同一人既是学生又是教师） | 源数据无 | 需人工确认；不自动合并 |
| 学号/工号格式异常 | 无 | 校验长度与字符；异常拒绝 |
| 教师职务（`app01_teacherposition`） | **未解决** | 新模型无教师职务字段；保留归档，待业务确认 |
| 管理员编号与既有账号冲突 | 无 | 同上 |

---

## 7. 回滚

`scripts/legacy_migration.py --rollback --settings=smass.settings_unified_verify`

实测：删除 3 学籍 / 6 账号 / 8 单元（仅本批次且无引用），
随后重新迁移与校验全部 PASS（`rollback.json`、`reapply.json`、`reverify.json`）。
