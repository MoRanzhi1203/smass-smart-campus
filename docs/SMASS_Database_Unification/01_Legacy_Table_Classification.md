# 01 旧表逐表分类

> 源库：`smass`（26 表，只读）
> 分类口径：MIGRATE / TRANSFORM / MERGE / REGENERATE / ARCHIVE_ONLY /
> DISCARD_CANDIDATE / UNRESOLVED
> 依据：表结构、允许读取的行数、`scripts/legacy_migration.py` 的实际映射与
> `inventory/models.json` 的新模型定义。**未凭表名猜测业务含义**。

---

## 1. 分类总表

| 旧表 | 行数 | 分类 | 目标 | 说明 |
|---|---|---|---|---|
| `app01_student` | 3 | TRANSFORM → MIGRATE | `Account(student)` + `StudentProfile` + `StudentRecord` | 学号→登录名；密码哈希继承；手机掩码；身份证不迁移；住宿写 `extra` |
| `app01_teacher` | 2 | TRANSFORM → MIGRATE | `Account(teacher)` + `TeacherProfile` + 学院关系 | 工号→登录名；密码继承；手机掩码 |
| `app01_admin` | 1 | MIGRATE | `Account(admin)` + `system_admin` | 管理员编号→登录名 |
| `app01_college` | 2 | MIGRATE | `OrganizationUnit(college, LEGACY-COL-*)` | 同名学院复用 |
| `app01_major` | 3 | MIGRATE | `OrganizationUnit(major)` | 上级=学院 |
| `app01_grade` | 3 | MIGRATE | `OrganizationUnit(grade)` | 仅展示；不改变班级单亲树 |
| `app01_classes` | 2 | MIGRATE + TRANSFORM | `OrganizationUnit(class)` + 辅导员 `Membership` | 上级=专业；`counsellor_id` → counselor 关系 |
| `app01_department` | 2 | MIGRATE | `OrganizationUnit(department)` | 团总支/学生会 |
| `app01_classcommittee` | 1 | MIGRATE | `OrganizationMembership(role=class_committee)` | 班委任职 |
| `app01_leaguecadres` | 1 | MIGRATE | `OrganizationMembership(role=league_cadre)` | 团学干部任职 |
| `app01_position` | 4 | **ARCHIVE_ONLY** | — | 教师职务字典；新模型无对应，未迁移 |
| `app01_teacherposition` | 2 | **UNRESOLVED** | — | 教师-职务关系；新模型无教师职务字段，无法确定是否等价于任职/职称 |
| `app01_building` | 0 | REGENERATE | — | 空表；新库由住宿配置重建（当前 `extra`） |
| `app01_dormitory` | 0 | REGENERATE | — | 空表 |
| `app01_dormitorynumber` | 0 | REGENERATE | — | 空表 |
| `app01_nation` | 0 | REGENERATE | — | 空表；民族字典 |
| `auth_user` | 0 | REGENERATE | Django `auth_user` | 新库由 migrate 创建；产品不使用 |
| `auth_group` | 0 | REGENERATE | `auth_group` | 新库由 `ensure_role_groups` 创建 |
| `auth_permission` | 88 | REGENERATE | `auth_permission` | 新库按模型重建 |
| `auth_group_permissions` | 0 | REGENERATE | 同表 | 新库重建 |
| `auth_user_groups` | 0 | REGENERATE | 同表 | 新库重建 |
| `auth_user_user_permissions` | 0 | REGENERATE | 同表 | 新库重建 |
| `django_content_type` | 22 | REGENERATE | 同表 | 新库重建（内容类型可能变化） |
| `django_migrations` | 22 | REGENERATE | 同表 | 新库按迁移图重建 |
| `django_admin_log` | 0 | DISCARD_CANDIDATE | — | 空表；Django 后台未启用，无需迁移 |
| `django_session` | 0 | DISCARD_CANDIDATE | — | 会话不迁移（无法复用且无价值） |

**统计**：MIGRATE/TRANSFORM 10 张、ARCHIVE_ONLY 1 张、UNRESOLVED 1 张、
REGENERATE 10 张、DISCARD_CANDIDATE 2 张、MERGE 0 张（本次数据无重复）。

---

## 2. 字段级分类（重要字段）

### 2.1 `app01_student`

| 字段 | 分类 | 去向/处理 |
|---|---|---|
| `id` | MIGRATE | `Account.login_name`、`StudentRecord.student_no` |
| `name` | MIGRATE | `Account.display_name`、`StudentRecord.name` |
| `password` | MIGRATE | `Account.password`（PBKDF2 直接继承；非 PBKDF2 设不可用+强制改密） |
| `sex` | MIGRATE | `StudentRecord.extra.sex` |
| `nation` | TRANSFORM | `extra.nation`（值为编号，未做字典展开） |
| `phone` | TRANSFORM | `StudentProfile.phone`（掩码 `138****1234`） |
| `cardID` | **DISCARD_CANDIDATE（敏感）** | 不迁移；`StudentProfile.card_id` 留空 |
| `qq` / `address` / `pinyin` | DISCARD_CANDIDATE | 不迁移（无新模型字段/低价值） |
| `building` / `dormitory` | TRANSFORM | `StudentRecord.extra.dormitory`（实测均为空） |
| `political` | MIGRATE | `extra.political` |
| `classes_id` | MIGRATE | `StudentRecord.unit`（班级） |

### 2.2 `app01_teacher`

| 字段 | 分类 | 去向 |
|---|---|---|
| `id` / `name` / `password` | MIGRATE | Account / TeacherProfile |
| `phone` | TRANSFORM | 掩码 |
| `cardID` | DISCARD_CANDIDATE（敏感） | 不迁移 |
| `college_id` | MIGRATE | `OrganizationMembership(role=teacher)` |
| `entry_time` / `qq` / `address` / `sex` / `nation` / `political` | ARCHIVE_ONLY | 新模型无对应字段 |

### 2.3 `app01_classes`

| 字段 | 分类 | 去向 |
|---|---|---|
| `name` | MIGRATE | `OrganizationUnit.name` |
| `counsellor_id` | TRANSFORM | `OrganizationMembership(role='counselor')` |
| `grade_id` | MIGRATE | 用于推断 `StudentRecord.enrolled_at`（年级名→年份）与 grade 单元 |
| `major_id` | MIGRATE | `OrganizationUnit.parent` |

---

## 3. 取舍清单（本轮不执行 DELETE）

| 项 | 分类 | 原因 | 处置 |
|---|---|---|---|
| `app01_position`（4 行） | ARCHIVE_ONLY | 新模型无教师职务字典；不影响产品 | 保留归档；如需展示再设计映射 |
| `app01_teacherposition`（2 行） | UNRESOLVED | 可能是职务/职称/任职，语义不明；不能猜 | 保留；由数据所有者确认后再决定 |
| 身份证号（3+2 行） | DISCARD_CANDIDATE | 敏感 PII，产品不需要 | 不迁移；真实值保留在正式库 |
| qq/address/pinyin（5 行） | DISCARD_CANDIDATE | 无消费方 | 不迁移 |
| `django_admin_log` / `django_session` | DISCARD_CANDIDATE | 空表/会话不可复用 | 不迁移 |
| 4 张空表（building/dormitory/dormitorynumber/nation） | REGENERATE | 无历史数据 | 新库由配置/未来住宿表重建 |

> 舍弃候选均记录在本清单，**未执行任何 DELETE**；正式库保持原样。

---

## 4. 未解决项与禁止猜测

| 项 | 为什么不能自动映射 |
|---|---|
| `app01_teacherposition` | 表名暗示"教师-职务"，但新模型没有教师职务/职称字段；
若映射到 `OrganizationMembership.role` 会改变语义（职务≠组织成员角色） |
| `app01_position` 的具体取值 | 4 行字典（如"教授/讲师"等），但新模型未建职称字段；
职称按技术决策只影响排课周上限，不产生授权 |
| `app01_nation` | 空表；若未来有值，应进入民族字典而非 `extra` |
| `political` 数值编码 | 迁移保留原始数值，未做中文枚举转换（避免猜测编码含义） |

---

## 5. 迁移数量对账（本轮实测）

| 指标 | 数值 |
|---|---|
| 源表总数 | 26 |
| 业务表（app01） | 16 |
| 有数据业务表 | 12（4 张为空） |
| 迁移账号 | 6（学生 3 + 教师 2 + 管理员 1） |
| 迁移学籍 | 3 |
| 迁移组织单元 | 12（学院 2 + 专业 3 + 年级 3 + 班级 2 + 部门 2） |
| 迁移任职关系 | 4（辅导员 2 + 班委 1 + 团学 1） |
| 转换（PII 掩码） | 5 条手机号 |
| 去重/合并 | 0 |
| 拒绝 | 0 |
| 未解决 | 1 张表（teacherposition） |
| 舍弃候选 | 3 张空表 + 2 张 Django 表 |

证据：`.local/evidence/unify/migration_apply.json`、`reconcile.json`。
