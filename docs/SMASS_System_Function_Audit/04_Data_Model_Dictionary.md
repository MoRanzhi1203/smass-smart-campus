# 数据模型字典

> 生成方式：`scripts/audit_system_inventory.py` 读取 Django 模型元数据，`scripts/audit_generate_docs.py` 渲染为 Markdown。
> 统计口径：有效模型 120 个（其中项目模型 114、Django 内置 6），自动 M2M 中间表 6 个单列在文末。

## 阅读说明

- **表**：模型实际对应的数据库表名；
- **字段**：类型、长度、可空、唯一、枚举值与关系目标；
- **敏感**列：字段名命中个人信息/凭据关键字，需按字段策略脱敏；
- **约束/索引**：模型 `Meta.constraints` 与 `Meta.indexes` 的实测值；
- **审计**：该模型是否有历史/审计表（仅在存在对应模型时标记）。

## 模块治理与数据归属

> 依据：各模块服务函数的权限判定、视图守卫、`r21_account/authorization.py` 与 `smass_workspace/permissions.py`。

| App | 定位 | 读取范围 | 写入角色 | 审计/历史 | app01 映射 |
|---|---|---|---|---|---|
| `app01` | 历史只读；迁移源 | 系统管理员（只读排查） | 不新增；仅迁移脚本读取 | AccountSecurityState / LoginDevice | → Account / StudentRecord / OrganizationUnit |
| `r21_account` | 统一身份 | 本人；管理员按范围 | 系统管理员 | AccountAuditLog / LoginAttempt | 承接 app01 三表账号 |
| `r22_account` | 双身份桥接 | 系统管理员 | 不写入（仅比对） | 无 | Legacy 映射校验 |
| `smass_organization` | 组织与学籍 | 超管全校；学院管理员本院；教师本人教学班；学生本人 | 超管；学院管理员受字段策略限制 | StudentRecordChange | College/Major/Classes → OrganizationUnit；Student → StudentRecord |
| `smass_academic` | 教务 | 全员按范围 | 超管 | EnrollmentHistory | 无直接映射（app01 无课程表） |
| `smass_workflow` | 流程审批 | 发起人/审批人/超管 | 发起人/审批人 | WorkflowEvent | 无 |
| `smass_analytics` | 指标报表 | 按 permission_roles | 超管 | MetricSnapshot | 无 |
| `smass_api` | 开放接口 | 持令牌客户端 | 超管签发 | Token / 幂等记录 | 无 |
| `smass_operations` | 运维 | 超管 | 超管 | AlertEvent / ReadinessProbe | 无 |
| `smass_scheduling` | 排课 | 教师/学生/管理员 | 超管 | ScheduleConflict / ScheduleRun.explanation | 无 |
| `smass_enrollment` | 学籍异动 | 学院管理员/超管；学生本人 | 学生提交；管理员审批 | 无独立事件表（状态字段） | 无 |
| `smass_attendance` | 考勤请假 | 教师/辅导员/管理员；学生本人 | 教师发起；学生提交请假 | 课程内建状态与审批字段 | 无 |
| `smass_activities` | 活动志愿 | 全员 | 超管/活动负责人；学生报名 | ActivityCredit 认定字段 | 无 |
| `smass_clubs` | 社团 | 全员 | 社团负责人/超管 | ClubPost 任职记录 | Department/LeagueCadres 可对应 |
| `smass_facilities` | 场地 | 全员 | 超管建档；师生预约；管理员审批 | RoomBooking 状态与审批字段 | 无 |
| `smass_forum` | 论坛公告 | 全员（按状态） | 超管/版主 | Report 处置记录 | 无 |
| `smass_finance` | 财务 | 学生本人；财务/超管 | 财务（can_finance）/超管 | LedgerEntry / RefundRequest | 无 |
| `smass_party` | 党建专项 | 授权用户（AccessGrant） | 超管/授权管理员 | AccessLog | 无 |
| `smass_portal` | 门户配置 | 全员 | 超管 | 无 | 无 |
| `smass_workspace` | 产品层（无模型） | — | — | — | — |

## 目录

- [app01 · 历史系统表（app01，升级迁移起点）](#app01)
- [r21_account · 统一账号与角色](#r21-account)
- [r22_account · 双身份桥接（R22）](#r22-account)
- [smass_organization · 组织与学籍](#smass-organization)
- [smass_academic · 学年学期、课程与教学班](#smass-academic)
- [smass_workflow · 流程、审批与通知](#smass-workflow)
- [smass_analytics · 指标与报表](#smass-analytics)
- [smass_api · 开放 API](#smass-api)
- [smass_operations · 运维监控与告警](#smass-operations)
- [smass_scheduling · 排课与课表](#smass-scheduling)
- [smass_enrollment · 分班、转专业与学籍异动](#smass-enrollment)
- [smass_attendance · 考勤与请假](#smass-attendance)
- [smass_activities · 活动、志愿与学分](#smass-activities)
- [smass_clubs · 社团与任职](#smass-clubs)
- [smass_facilities · 场地与预约](#smass-facilities)
- [smass_forum · 论坛、公告与举报](#smass-forum)
- [smass_finance · 账单、缴费与退费](#smass-finance)
- [smass_party · 党建与专项组织](#smass-party)
- [smass_portal · 门户配置](#smass-portal)

---

## app01

### 历史系统表（app01，升级迁移起点）

原始校园系统的三张账号表（Admin/Student/Teacher）及组织、寝室、职务表。产品登录已不使用这些表，但历史数据是升级迁移的起点；迁移脚本把其中的学院/专业/班级/学生/教师/管理员映射到统一模型。

#### `AccountSecurityState`（表 `app01_account_security_state`）

- 业务名称：账号安全状态
- 主键：`id`
- 排序：未设置
- 敏感字段：`must_change_password`、`legacy_hash_pending`、`password_changed_at`、`temp_password_expires_at`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account_type` | CharField max=16 choices=admin/student/teacher | 否 | 否 | 账号类型 |
| `account_id` | CharField max=32 | 否 | 否 | 账号标识 |
| `must_change_password` | BooleanField | 否 | 否 | 需强制改密 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `legacy_hash_pending` | BooleanField | 否 | 否 | 仍持有历史MD5 |
| `password_changed_at` | DateTimeField null blank | 是 | 否 | 最近改密时间 |
| `temp_password_expires_at` | DateTimeField null blank | 是 | 否 | 临时口令到期 |
| `session_epoch` | PositiveIntegerField | 否 | 否 | 会话世代 |
| `last_reset_by` | CharField max=32 blank | 否 | 否 | 最近重置操作者 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

约束与索引：

- 约束 `uniq_app01_account_security_state`（UniqueConstraint）：fields=['account_type', 'account_id'] condition=None
- 索引 `idx_ass_must_change`：fields=['must_change_password'] condition=None
- 索引 `idx_ass_legacy_pending`：fields=['legacy_hash_pending'] condition=None
- 索引 `idx_ass_is_active`：fields=['is_active'] condition=None

#### `Admin`（表 `app01_admin`）

- 业务名称：admin
- 主键：`id`
- 排序：未设置
- 敏感字段：`password`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | CharField max=3 unique | 否 | 是 | 账号 |
| `name` | CharField max=16 | 否 | 否 | 姓名 |
| `password` | CharField max=128 | 否 | 否 | 密码 |

#### `Building`（表 `app01_building`）

- 业务名称：building
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=100 | 否 | 否 | 楼栋 |

#### `ClassCommittee`（表 `app01_classcommittee`）

- 业务名称：class committee
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | OneToOneField unique → app01.Student on_delete=CASCADE | 否 | 是 | 学号 |
| `classes` | ForeignKey → app01.Classes on_delete=CASCADE | 否 | 否 | 班级 |
| `committee` | SmallIntegerField choices=0/1/2/3/4/5/6/7 | 否 | 否 | 职务 |

关系：

- `id` → `app01.Student`（related_name=`默认`，on_delete=CASCADE）
- `classes` → `app01.Classes`（related_name=`默认`，on_delete=CASCADE）

#### `Classes`（表 `app01_classes`）

- 业务名称：classes
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=100 | 否 | 否 | 班级 |
| `grade` | ForeignKey null → app01.Grade on_delete=SET_NULL | 是 | 否 | 年级 |
| `major` | ForeignKey null → app01.Major on_delete=SET_NULL | 是 | 否 | 专业 |
| `counsellor` | ForeignKey null → app01.Teacher on_delete=SET_NULL | 是 | 否 | 辅导员 |

关系：

- `grade` → `app01.Grade`（related_name=`默认`，on_delete=SET_NULL）
- `major` → `app01.Major`（related_name=`默认`，on_delete=SET_NULL）
- `counsellor` → `app01.Teacher`（related_name=`默认`，on_delete=SET_NULL）

#### `College`（表 `app01_college`）

- 业务名称：college
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=10 | 否 | 否 | 学院 |

#### `Department`（表 `app01_department`）

- 业务名称：department
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `department` | CharField max=10 | 否 | 否 | 部门 |
| `faction` | SmallIntegerField choices=1/2 | 否 | 否 | 团总支/学生会 |
| `college` | ForeignKey null blank → app01.College on_delete=CASCADE | 是 | 否 | 学院 |
| `level` | SmallIntegerField choices=0/1 | 否 | 否 | 院/校级 |

关系：

- `college` → `app01.College`（related_name=`默认`，on_delete=CASCADE）

#### `Dormitory`（表 `app01_dormitory`）

- 业务名称：dormitory
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `number` | CharField max=100 | 否 | 否 | 寝室号 |

#### `DormitoryNumber`（表 `app01_dormitorynumber`）

- 业务名称：dormitory number
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `building` | ForeignKey → app01.Building on_delete=CASCADE | 否 | 否 | 楼栋 |
| `dormitory` | ForeignKey → app01.Dormitory on_delete=CASCADE | 否 | 否 | 寝室号 |

关系：

- `building` → `app01.Building`（related_name=`默认`，on_delete=CASCADE）
- `dormitory` → `app01.Dormitory`（related_name=`默认`，on_delete=CASCADE）

#### `Grade`（表 `app01_grade`）

- 业务名称：grade
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=100 | 否 | 否 | 年级 |

#### `LeagueCadres`（表 `app01_leaguecadres`）

- 业务名称：league cadres
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | OneToOneField unique → app01.Student on_delete=CASCADE | 否 | 是 | 学号 |
| `department` | ForeignKey → app01.Department on_delete=CASCADE | 否 | 否 | 部门 |
| `duties` | SmallIntegerField choices=0/1/2 | 否 | 否 | 职务 |

关系：

- `id` → `app01.Student`（related_name=`默认`，on_delete=CASCADE）
- `department` → `app01.Department`（related_name=`默认`，on_delete=CASCADE）

#### `LoginDevice`（表 `app01_login_device`）

- 业务名称：登录设备
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `device_id` | CharField max=64 unique | 否 | 是 | 设备标识 |
| `user_id` | CharField max=32 | 否 | 否 | 用户标识 |
| `role` | CharField max=16 blank | 否 | 否 | 登录角色 |
| `session_key` | CharField max=64 blank | 否 | 否 | 会话键 |
| `ip` | CharField max=64 blank | 否 | 否 | 来源 IP |
| `user_agent` | CharField max=200 blank | 否 | 否 | 客户端 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `last_seen` | DateTimeField blank | 否 | 否 | 最近活动 |
| `revoked_at` | DateTimeField null blank | 是 | 否 | 撤销时间 |

约束与索引：

- 索引 `idx_login_dev_user`：fields=['user_id', 'revoked_at'] condition=None

#### `Major`（表 `app01_major`）

- 业务名称：major
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `college` | ForeignKey null → app01.College on_delete=SET_NULL | 是 | 否 | 学院 |
| `name` | CharField max=100 | 否 | 否 | 专业 |

关系：

- `college` → `app01.College`（related_name=`默认`，on_delete=SET_NULL）

#### `Nation`（表 `app01_nation`）

- 业务名称：nation
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `nationality` | CharField max=10 | 否 | 否 | 民族 |

#### `Position`（表 `app01_position`）

- 业务名称：position
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=6 | 否 | 否 | 教师职务 |

#### `Student`（表 `app01_student`）

- 业务名称：student
- 主键：`id`
- 排序：未设置
- 敏感字段：`password`、`phone`、`qq`、`address`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | CharField max=10 unique | 否 | 是 | 学号 |
| `name` | CharField max=16 | 否 | 否 | 姓名 |
| `password` | CharField max=128 | 否 | 否 | 密码 |
| `pinyin` | CharField max=32 null | 是 | 否 | 拼音 |
| `sex` | SmallIntegerField null choices=0/1 | 是 | 否 | 性别 |
| `nation` | CharField max=10 null | 是 | 否 | 民族 |
| `classes` | ForeignKey null → app01.Classes on_delete=SET_NULL | 是 | 否 | 班级 |
| `cardID` | CharField max=18 | 否 | 否 | 身份证号 |
| `phone` | CharField max=11 null | 是 | 否 | 手机号 |
| `qq` | CharField max=11 null | 是 | 否 | QQ号 |
| `address` | CharField max=64 null | 是 | 否 | 详细地址 |
| `building` | CharField max=3 null | 是 | 否 | 楼栋 |
| `dormitory` | CharField max=3 null | 是 | 否 | 寝室号 |
| `political` | SmallIntegerField choices=0/1/2 | 否 | 否 | 政治面貌 |

关系：

- `classes` → `app01.Classes`（related_name=`默认`，on_delete=SET_NULL）

#### `Teacher`（表 `app01_teacher`）

- 业务名称：teacher
- 主键：`id`
- 排序：未设置
- 敏感字段：`password`、`phone`、`qq`、`address`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | CharField max=7 unique | 否 | 是 | 教职员工编号 |
| `name` | CharField max=16 | 否 | 否 | 姓名 |
| `password` | CharField max=128 | 否 | 否 | 密码 |
| `pinyin` | CharField max=32 null | 是 | 否 | 拼音 |
| `sex` | SmallIntegerField choices=0/1 | 否 | 否 | 性别 |
| `nation` | CharField max=10 null | 是 | 否 | 民族 |
| `cardID` | CharField max=18 | 否 | 否 | 身份证号 |
| `phone` | CharField max=11 | 否 | 否 | 手机号 |
| `qq` | CharField max=11 | 否 | 否 | QQ号 |
| `address` | CharField max=64 | 否 | 否 | 详细地址 |
| `entry_time` | DateField null | 是 | 否 | 入职时间 |
| `college` | ForeignKey null → app01.College on_delete=SET_NULL | 是 | 否 | 院系 |
| `political` | SmallIntegerField choices=0/1/2 | 否 | 否 | 政治面貌 |
| `position` | ManyToManyField → app01.Position | 否 | 否 | 教师职务 |

关系：

- `college` → `app01.College`（related_name=`默认`，on_delete=SET_NULL）
- `position` → `app01.Position`（related_name=`Position`，on_delete=—）

#### `TeacherPosition`（表 `app01_teacherposition`）

- 业务名称：teacher position
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `teacher` | ForeignKey → app01.Teacher on_delete=CASCADE | 否 | 否 | 教师 |
| `position` | ForeignKey → app01.Position on_delete=CASCADE | 否 | 否 | 教师职务 |

关系：

- `teacher` → `app01.Teacher`（related_name=`默认`，on_delete=CASCADE）
- `position` → `app01.Position`（related_name=`默认`，on_delete=CASCADE）


---

## r21_account

### 统一账号与角色

统一身份权威：Account（登录）、AccountRole（角色）、StudentProfile/TeacherProfile（业务档案轻量映射）、LegacyAccountLink（历史账号锚点）、AccountAuditLog/LoginAttempt（审计）。

#### `Account`（表 `r21_account_account`）

- 业务名称：R2.1 统一账号
- 主键：`id`
- 排序：未设置
- 敏感字段：`password`、`must_change_password`、`password_changed_at`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `password` | CharField max=128 | 否 | 否 | 密码 |
| `last_login` | DateTimeField null blank | 是 | 否 | 上次登录 |
| `is_superuser` | BooleanField | 否 | 否 | 超级用户状态 |
| `login_name` | CharField max=32 unique | 否 | 是 | 登录名 |
| `display_name` | CharField max=32 | 否 | 否 | 显示名 |
| `person_type` | CharField max=16 choices=admin/teacher/student | 否 | 否 | 人员类型 |
| `is_active` | BooleanField | 否 | 否 | 账号可用 |
| `is_staff` | BooleanField | 否 | 否 | 可进管理后台 |
| `must_change_password` | BooleanField | 否 | 否 | 需强制改密 |
| `password_changed_at` | DateTimeField null blank | 是 | 否 | 密码变更时间 |
| `scope_college` | CharField max=100 blank | 否 | 否 | 授权学院 |
| `deactivated_at` | DateTimeField null blank | 是 | 否 | 停用时间 |
| `deactivated_reason` | CharField max=64 blank | 否 | 否 | 停用原因 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |
| `groups` | ManyToManyField blank → auth.Group | 否 | 否 | 角色组 |
| `user_permissions` | ManyToManyField blank → auth.Permission | 否 | 否 | 附加权限 |

关系：

- `groups` → `auth.Group`（related_name=`r21_accounts`，on_delete=—）
- `user_permissions` → `auth.Permission`（related_name=`r21_accounts`，on_delete=—）

约束与索引：

- 索引 `r21_account_person__25768c_idx`：fields=['person_type', 'is_active'] condition=None
- 索引 `r21_account_scope_c_80d3a6_idx`：fields=['scope_college'] condition=None

#### `AccountAuditLog`（表 `r21_account_accountauditlog`）

- 业务名称：账号审计
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `action` | CharField max=32 choices=create/backfill/login/login_failed/login_locked/password_change/password_reset/role_grant | 否 | 否 | 动作 |
| `actor` | CharField max=32 blank | 否 | 否 | 操作者 |
| `target` | CharField max=32 blank | 否 | 否 | 目标账号 |
| `detail` | CharField max=255 blank | 否 | 否 | 说明 |
| `ip` | CharField max=45 blank | 否 | 否 | 来源 IP |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `r21_account_action_d0d515_idx`：fields=['action', 'created_at'] condition=None

#### `AccountRole`（表 `r21_account_accountrole`）

- 业务名称：角色授予
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 账号 |
| `role` | CharField max=32 choices=system_admin/college_admin/teacher/student | 否 | 否 | 角色 |
| `granted_at` | DateTimeField blank | 否 | 否 | 授予时间 |
| `granted_by` | CharField max=32 blank | 否 | 否 | 授予人 |
| `revoked_at` | DateTimeField null blank | 是 | 否 | 撤销时间 |
| `revoked_by` | CharField max=32 blank | 否 | 否 | 撤销人 |

关系：

- `account` → `r21_account.Account`（related_name=`roles`，on_delete=CASCADE）

约束与索引：

- 索引 `r21_account_account_a5aa86_idx`：fields=['account', 'revoked_at'] condition=None

#### `LegacyAccountLink`（表 `r21_account_legacyaccountlink`）

- 业务名称：旧账号映射
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | OneToOneField unique → r21_account.Account on_delete=CASCADE | 否 | 是 | 账号 |
| `source_table` | CharField max=32 | 否 | 否 | 来源表 |
| `source_pk` | CharField max=32 | 否 | 否 | 来源主键 |
| `backfilled_at` | DateTimeField blank | 否 | 否 | 回填时间 |
| `checksum` | CharField max=32 blank | 否 | 否 | 密码哈希指纹（不可逆） |

关系：

- `account` → `r21_account.Account`（related_name=`legacy_link`，on_delete=CASCADE）

约束与索引：

- 约束 `r21_uniq_legacy_origin`（UniqueConstraint）：fields=['source_table', 'source_pk'] condition=None
- 索引 `r21_account_source__974d9d_idx`：fields=['source_table', 'source_pk'] condition=None

#### `LoginAttempt`（表 `r21_account_loginattempt`）

- 业务名称：登录尝试
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `login_name` | CharField max=32 | 否 | 否 | 登录名 |
| `ip` | CharField max=45 blank | 否 | 否 | 来源 IP |
| `success` | BooleanField | 否 | 否 | 是否成功 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `r21_account_login_n_5179fe_idx`：fields=['login_name', 'ip', 'created_at'] condition=None
- 索引 `r21_account_login_n_c2c546_idx`：fields=['login_name', 'created_at'] condition=None

#### `StudentProfile`（表 `r21_account_studentprofile`）

- 业务名称：学生档案
- 主键：`id`
- 排序：未设置
- 敏感字段：`phone`、`card_id`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | OneToOneField unique → r21_account.Account on_delete=CASCADE | 否 | 是 | 账号 |
| `student_no` | CharField max=10 unique | 否 | 是 | 学号 |
| `name` | CharField max=16 | 否 | 否 | 姓名 |
| `college_name` | CharField max=100 blank | 否 | 否 | 学院 |
| `classes_name` | CharField max=100 blank | 否 | 否 | 班级 |
| `phone` | CharField max=11 blank | 否 | 否 | 手机号 |
| `card_id` | CharField max=18 blank | 否 | 否 | 身份证号 |

关系：

- `account` → `r21_account.Account`（related_name=`student_profile`，on_delete=CASCADE）

#### `TeacherProfile`（表 `r21_account_teacherprofile`）

- 业务名称：教师档案
- 主键：`id`
- 排序：未设置
- 敏感字段：`phone`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | OneToOneField unique → r21_account.Account on_delete=CASCADE | 否 | 是 | 账号 |
| `teacher_no` | CharField max=7 unique | 否 | 是 | 工号 |
| `name` | CharField max=16 | 否 | 否 | 姓名 |
| `college_name` | CharField max=100 blank | 否 | 否 | 学院 |
| `phone` | CharField max=11 blank | 否 | 否 | 手机号 |

关系：

- `account` → `r21_account.Account`（related_name=`teacher_profile`，on_delete=CASCADE）


---

## r22_account

### 双身份桥接（R22）

R22 双身份桥接表，用于在正式切换前比对旧 app01 账号与新账号的映射状态；产品路径不依赖它做登录，迁移脚本也不写入该表。

#### `AccountAuditEvent`（表 `r22_account_accountauditevent`）

- 业务名称：R2.2 账号审计事件
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `action` | CharField max=48 | 否 | 否 | 动作 |
| `outcome` | CharField max=16 choices=success/denied/error | 否 | 否 | 结果 |
| `actor_kind` | CharField max=16 choices=account/legacy/system/unknown | 否 | 否 | 操作者类型 |
| `actor_login` | CharField max=32 blank | 否 | 否 | 操作者登录名 |
| `target` | CharField max=32 blank | 否 | 否 | 目标类型 |
| `target_id` | CharField max=64 blank | 否 | 否 | 目标标识 |
| `context` | JSONField blank | 否 | 否 | 上下文 |
| `ip` | CharField max=45 blank | 否 | 否 | 来源 IP |
| `request_id` | CharField max=36 blank | 否 | 否 | 请求关联 ID |
| `batch_id` | CharField max=36 blank | 否 | 否 | 批次 ID |
| `operation` | CharField max=16 blank | 否 | 否 | 批次操作 |
| `source_batch_id` | CharField max=36 blank | 否 | 否 | 来源批次 ID |
| `counts` | JSONField blank | 否 | 否 | 脱敏计数 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `r22_account_action_3f752d_idx`：fields=['action', 'outcome', 'created_at'] condition=None
- 索引 `r22_account_actor_l_0d2a2f_idx`：fields=['actor_login', 'created_at'] condition=None
- 索引 `r22_account_batch_i_2d1d80_idx`：fields=['batch_id', 'created_at'] condition=None


---

## smass_organization

### 组织与学籍

组织树（学院/专业/年级/班级/部门）、学籍档案、学籍变更历史、字段策略、导入批次。

#### `DataImportJob`（表 `smass_organization_dataimportjob`）

- 业务名称：导入批次
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `batch_id` | UUIDField max=32 unique | 否 | 是 | 批次 |
| `kind` | CharField max=32 | 否 | 否 | 类型 |
| `status` | CharField max=16 choices=pending/previewed/committed/failed | 否 | 否 | 状态 |
| `total_rows` | IntegerField | 否 | 否 | 总行数 |
| `success_rows` | IntegerField | 否 | 否 | 成功行数 |
| `error_rows` | IntegerField | 否 | 否 | 错误行数 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建者 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `committed_at` | DateTimeField null blank | 是 | 否 | 提交时间 |

约束与索引：

- 索引 `smass_organ_status_758c76_idx`：fields=['status', 'created_at'] condition=None

#### `DataImportRowError`（表 `smass_organization_dataimportrowerror`）

- 业务名称：导入错误行
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `job` | ForeignKey → smass_organization.DataImportJob on_delete=CASCADE | 否 | 否 | 批次 |
| `row_number` | IntegerField | 否 | 否 | 行号 |
| `column` | CharField max=64 blank | 否 | 否 | 列 |
| `error_code` | CharField max=32 | 否 | 否 | 错误码 |
| `message` | CharField max=255 blank | 否 | 否 | 说明 |

关系：

- `job` → `smass_organization.DataImportJob`（related_name=`errors`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_organ_job_id_2d08ee_idx`：fields=['job', 'row_number'] condition=None

#### `OrganizationMembership`（表 `smass_organization_organizationmembership`）

- 业务名称：组织成员关系
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 账号 |
| `unit` | ForeignKey → smass_organization.OrganizationUnit on_delete=CASCADE | 否 | 否 | 组织 |
| `role` | CharField max=32 blank | 否 | 否 | 在组织中的角色 |
| `started_at` | DateField null blank | 是 | 否 | 开始日期 |
| `ended_at` | DateField null blank | 是 | 否 | 结束日期 |

关系：

- `account` → `r21_account.Account`（related_name=`org_memberships`，on_delete=CASCADE）
- `unit` → `smass_organization.OrganizationUnit`（related_name=`memberships`，on_delete=CASCADE）

约束与索引：

- 约束 `r4_uniq_active_membership`（UniqueConstraint）：fields=['account', 'unit'] condition=<Q: (AND: ('ended_at__isnull', True))>
- 索引 `smass_organ_unit_id_358b28_idx`：fields=['unit', 'ended_at'] condition=None

#### `OrganizationUnit`（表 `smass_organization_organizationunit`）

- 业务名称：组织单元
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `unit_type` | CharField max=16 choices=college/major/grade/class/department | 否 | 否 | 类型 |
| `parent` | ForeignKey null blank → smass_organization.OrganizationUnit on_delete=PROTECT | 是 | 否 | 上级 |
| `status` | CharField max=16 | 否 | 否 | 状态 |
| `sort_order` | IntegerField | 否 | 否 | 排序 |
| `valid_from` | DateField null blank | 是 | 否 | 生效日期 |
| `valid_to` | DateField null blank | 是 | 否 | 失效日期 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `parent` → `smass_organization.OrganizationUnit`（related_name=`children`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_organ_unit_ty_45f99d_idx`：fields=['unit_type', 'status'] condition=None
- 索引 `smass_organ_parent__89464a_idx`：fields=['parent', 'sort_order'] condition=None

#### `StudentFieldDefinition`（表 `smass_organization_studentfielddefinition`）

- 业务名称：学生字段定义
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 字段编码 |
| `label` | CharField max=100 | 否 | 否 | 显示名 |
| `data_type` | CharField max=16 choices=string/int/date/bool | 否 | 否 | 类型 |
| `required` | BooleanField | 否 | 否 | 必填 |
| `is_sensitive` | BooleanField | 否 | 否 | 敏感字段 |
| `visible_roles` | JSONField blank | 否 | 否 | 可见角色 |
| `editable_roles` | JSONField blank | 否 | 否 | 可编辑角色 |
| `sort_order` | IntegerField | 否 | 否 | 排序 |
| `active` | BooleanField | 否 | 否 | 启用 |

约束与索引：

- 索引 `smass_organ_active_7c7cce_idx`：fields=['active', 'sort_order'] condition=None

#### `StudentRecord`（表 `smass_organization_studentrecord`）

- 业务名称：学籍档案
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `student_no` | CharField max=20 unique | 否 | 是 | 学号 |
| `name` | CharField max=32 | 否 | 否 | 姓名 |
| `account` | ForeignKey null blank → r21_account.Account on_delete=SET_NULL | 是 | 否 | 关联账号 |
| `unit` | ForeignKey null blank → smass_organization.OrganizationUnit on_delete=PROTECT | 是 | 否 | 所属组织 |
| `status` | CharField max=16 choices=enrolled/suspended/graduated/withdrawn | 否 | 否 | 学籍状态 |
| `enrolled_at` | DateField null blank | 是 | 否 | 入学日期 |
| `extra` | JSONField blank | 否 | 否 | 扩展字段 |
| `version` | IntegerField | 否 | 否 | 版本号（乐观锁） |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `account` → `r21_account.Account`（related_name=`student_records`，on_delete=SET_NULL）
- `unit` → `smass_organization.OrganizationUnit`（related_name=`students`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_organ_unit_id_e02adc_idx`：fields=['unit', 'status'] condition=None
- 索引 `smass_organ_status_37c060_idx`：fields=['status'] condition=None

#### `StudentRecordChange`（表 `smass_organization_studentrecordchange`）

- 业务名称：档案变更
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=CASCADE | 否 | 否 | 档案 |
| `field_name` | CharField max=64 | 否 | 否 | 字段 |
| `old_value` | CharField max=255 blank | 否 | 否 | 原值 |
| `new_value` | CharField max=255 blank | 否 | 否 | 新值 |
| `reason` | CharField max=255 blank | 否 | 否 | 原因 |
| `changed_by` | CharField max=32 blank | 否 | 否 | 操作者 |
| `batch_id` | CharField max=36 blank | 否 | 否 | 批次 |
| `changed_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`changes`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_organ_record__82e403_idx`：fields=['record', 'changed_at'] condition=None


---

## smass_academic

### 学年学期、课程与教学班

学年、学期、课程、教学班、任课分配、选课与选课历史。

#### `AcademicTerm`（表 `smass_academic_academicterm`）

- 业务名称：学期
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `year` | ForeignKey → smass_academic.AcademicYear on_delete=CASCADE | 否 | 否 | 学年 |
| `semester` | CharField max=1 choices=1/2/S | 否 | 否 | 学期 |
| `name` | CharField max=32 blank | 否 | 否 | 显示名 |
| `start_date` | DateField | 否 | 否 | 开始日期 |
| `end_date` | DateField | 否 | 否 | 结束日期 |
| `is_active` | BooleanField | 否 | 否 | 当前学期 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `year` → `smass_academic.AcademicYear`（related_name=`terms`，on_delete=CASCADE）

约束与索引：

- 约束 `r5_uniq_term_per_year`（UniqueConstraint）：fields=['year', 'semester'] condition=None
- 约束 `r5_term_range_valid`（CheckConstraint）：fields=[] condition=<Q: (AND: ('end_date__gt', F(start_date)))>
- 约束 `r5_uniq_active_term`（UniqueConstraint）：fields=['is_active'] condition=<Q: (AND: ('is_active', True))>
- 索引 `smass_acade_year_id_f5a4fb_idx`：fields=['year', 'semester'] condition=None

#### `AcademicYear`（表 `smass_academic_academicyear`）

- 业务名称：学年
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=16 unique | 否 | 是 | 学年编码 |
| `start_date` | DateField | 否 | 否 | 开始日期 |
| `end_date` | DateField | 否 | 否 | 结束日期 |
| `is_active` | BooleanField | 否 | 否 | 当前学年 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 约束 `r5_year_range_valid`（CheckConstraint）：fields=[] condition=<Q: (AND: ('end_date__gt', F(start_date)))>
- 约束 `r5_uniq_active_year`（UniqueConstraint）：fields=['is_active'] condition=<Q: (AND: ('is_active', True))>
- 索引 `smass_acade_is_acti_db8b41_idx`：fields=['is_active', 'start_date'] condition=None

#### `Course`（表 `smass_academic_course`）

- 业务名称：课程
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=32 unique | 否 | 是 | 课程编码 |
| `title` | CharField max=128 | 否 | 否 | 课程名称 |
| `credit` | DecimalField null blank | 是 | 否 | 学分 |
| `course_type` | CharField max=32 blank | 否 | 否 | 课程类型 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

约束与索引：

- 索引 `smass_acade_is_acti_07627c_idx`：fields=['is_active', 'code'] condition=None

#### `Enrollment`（表 `smass_academic_enrollment`）

- 业务名称：修读关系
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `section` | ForeignKey → smass_academic.TeachingSection on_delete=CASCADE | 否 | 否 | 教学班 |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 学生账号 |
| `status` | CharField max=16 choices=enrolled/dropped | 否 | 否 | 状态 |
| `enrolled_at` | DateTimeField blank | 否 | 否 | 选课时间 |
| `changed_at` | DateTimeField blank | 否 | 否 | 状态变更时间 |

关系：

- `section` → `smass_academic.TeachingSection`（related_name=`enrollments`，on_delete=CASCADE）
- `account` → `r21_account.Account`（related_name=`enrollments`，on_delete=CASCADE）

约束与索引：

- 约束 `r5_uniq_enrollment`（UniqueConstraint）：fields=['section', 'account'] condition=None
- 索引 `smass_acade_section_b12c03_idx`：fields=['section', 'status'] condition=None

#### `EnrollmentHistory`（表 `smass_academic_enrollmenthistory`）

- 业务名称：修读历史
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `enrollment` | ForeignKey → smass_academic.Enrollment on_delete=CASCADE | 否 | 否 | 修读 |
| `old_status` | CharField max=16 blank | 否 | 否 | 原状态 |
| `new_status` | CharField max=16 | 否 | 否 | 新状态 |
| `changed_by` | CharField max=32 blank | 否 | 否 | 操作者 |
| `changed_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `enrollment` → `smass_academic.Enrollment`（related_name=`history`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_acade_enrollm_6ade5a_idx`：fields=['enrollment', 'changed_at'] condition=None

#### `TeachingAssignment`（表 `smass_academic_teachingassignment`）

- 业务名称：任课关系
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `section` | ForeignKey → smass_academic.TeachingSection on_delete=CASCADE | 否 | 否 | 教学班 |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 教师账号 |
| `assigned_at` | DateTimeField blank | 否 | 否 | 分配时间 |
| `revoked_at` | DateTimeField null blank | 是 | 否 | 撤销时间 |
| `assigned_by` | CharField max=32 blank | 否 | 否 | 分配人 |

关系：

- `section` → `smass_academic.TeachingSection`（related_name=`assignments`，on_delete=CASCADE）
- `account` → `r21_account.Account`（related_name=`teaching_assignments`，on_delete=CASCADE）

约束与索引：

- 约束 `r5_uniq_active_assignment`（UniqueConstraint）：fields=['section', 'account'] condition=<Q: (AND: ('revoked_at__isnull', True))>
- 索引 `smass_acade_account_05099f_idx`：fields=['account', 'revoked_at'] condition=None

#### `TeachingSection`（表 `smass_academic_teachingsection`）

- 业务名称：教学班
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `term` | ForeignKey → smass_academic.AcademicTerm on_delete=PROTECT | 否 | 否 | 学期 |
| `course` | ForeignKey → smass_academic.Course on_delete=PROTECT | 否 | 否 | 课程 |
| `code` | CharField max=32 | 否 | 否 | 教学班号 |
| `capacity` | IntegerField | 否 | 否 | 容量 |
| `status` | CharField max=16 choices=open/closed | 否 | 否 | 状态 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `term` → `smass_academic.AcademicTerm`（related_name=`sections`，on_delete=PROTECT）
- `course` → `smass_academic.Course`（related_name=`sections`，on_delete=PROTECT）

约束与索引：

- 约束 `r5_uniq_section_code`（UniqueConstraint）：fields=['term', 'course', 'code'] condition=None
- 约束 `r5_section_capacity_nonneg`（CheckConstraint）：fields=[] condition=<Q: (AND: ('capacity__gte', 0))>
- 索引 `smass_acade_term_id_931927_idx`：fields=['term', 'status'] condition=None


---

## smass_workflow

### 流程、审批与通知

流程定义/版本/节点/流转、实例、事件、待办、通知。

#### `ApprovalTask`（表 `smass_workflow_approvaltask`）

- 业务名称：审批任务
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `instance` | ForeignKey → smass_workflow.WorkflowInstance on_delete=CASCADE | 否 | 否 | 实例 |
| `node` | ForeignKey → smass_workflow.WorkflowNode on_delete=CASCADE | 否 | 否 | 节点 |
| `assignee` | CharField max=32 blank | 否 | 否 | 处理人 |
| `status` | CharField max=16 choices=open/done/cancelled | 否 | 否 | 状态 |
| `idempotency_key` | CharField max=64 blank | 否 | 否 | 幂等键 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `completed_at` | DateTimeField null blank | 是 | 否 | 完成时间 |

关系：

- `instance` → `smass_workflow.WorkflowInstance`（related_name=`tasks`，on_delete=CASCADE）
- `node` → `smass_workflow.WorkflowNode`（related_name=`tasks`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_workf_assigne_88b6e9_idx`：fields=['assignee', 'status'] condition=None

#### `Notification`（表 `smass_workflow_notification`）

- 业务名称：站内通知
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `recipient` | CharField max=32 | 否 | 否 | 接收人 |
| `title` | CharField max=128 | 否 | 否 | 标题 |
| `body` | CharField max=512 blank | 否 | 否 | 内容 |
| `level` | CharField max=16 choices=info/warning | 否 | 否 | 级别 |
| `event_key` | CharField max=96 blank | 否 | 否 | 事件键（幂等） |
| `is_read` | BooleanField | 否 | 否 | 已读 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 约束 `r6_uniq_notification_event`（UniqueConstraint）：fields=['recipient', 'event_key'] condition=None
- 索引 `smass_workf_recipie_86131a_idx`：fields=['recipient', 'is_read'] condition=None

#### `WorkflowDefinition`（表 `smass_workflow_workflowdefinition`）

- 业务名称：流程定义
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 流程编码 |
| `name` | CharField max=128 | 否 | 否 | 流程名称 |
| `description` | CharField max=255 blank | 否 | 否 | 说明 |
| `is_active` | BooleanField | 否 | 否 | 已启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_workf_code_2d5c46_idx`：fields=['code', 'is_active'] condition=None

#### `WorkflowEvent`（表 `smass_workflow_workflowevent`）

- 业务名称：流程事件
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `instance` | ForeignKey → smass_workflow.WorkflowInstance on_delete=CASCADE | 否 | 否 | 实例 |
| `action` | CharField max=32 | 否 | 否 | 动作 |
| `from_status` | CharField max=16 blank | 否 | 否 | 原状态 |
| `to_status` | CharField max=16 blank | 否 | 否 | 新状态 |
| `from_node` | CharField max=64 blank | 否 | 否 | 原节点 |
| `to_node` | CharField max=64 blank | 否 | 否 | 新节点 |
| `actor` | CharField max=32 blank | 否 | 否 | 操作者 |
| `reason` | CharField max=255 blank | 否 | 否 | 原因 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `instance` → `smass_workflow.WorkflowInstance`（related_name=`events`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_workf_instanc_538e21_idx`：fields=['instance', 'created_at'] condition=None

#### `WorkflowInstance`（表 `smass_workflow_workflowinstance`）

- 业务名称：流程实例
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `version` | ForeignKey → smass_workflow.WorkflowVersion on_delete=PROTECT | 否 | 否 | 版本 |
| `subject_type` | CharField max=64 | 否 | 否 | 业务类型 |
| `subject_id` | CharField max=64 | 否 | 否 | 业务标识 |
| `status` | CharField max=16 choices=draft/pending/approved/rejected/withdrawn | 否 | 否 | 状态 |
| `current_node` | ForeignKey null blank → smass_workflow.WorkflowNode on_delete=SET_NULL | 是 | 否 | 当前节点 |
| `created_by` | CharField max=32 blank | 否 | 否 | 发起人 |
| `version_no` | IntegerField | 否 | 否 | 乐观锁版本 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `version` → `smass_workflow.WorkflowVersion`（related_name=`instances`，on_delete=PROTECT）
- `current_node` → `smass_workflow.WorkflowNode`（related_name=`current_instances`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_workf_status_3b0226_idx`：fields=['status', 'created_at'] condition=None
- 索引 `smass_workf_subject_2ef06e_idx`：fields=['subject_type', 'subject_id'] condition=None

#### `WorkflowNode`（表 `smass_workflow_workflownode`）

- 业务名称：流程节点
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `version` | ForeignKey → smass_workflow.WorkflowVersion on_delete=CASCADE | 否 | 否 | 版本 |
| `code` | CharField max=64 | 否 | 否 | 节点编码 |
| `name` | CharField max=128 | 否 | 否 | 节点名称 |
| `node_type` | CharField max=16 choices=start/approval/end | 否 | 否 | 类型 |
| `order` | IntegerField | 否 | 否 | 顺序 |

关系：

- `version` → `smass_workflow.WorkflowVersion`（related_name=`nodes`，on_delete=CASCADE）

约束与索引：

- 约束 `r6_uniq_node_code`（UniqueConstraint）：fields=['version', 'code'] condition=None
- 索引 `smass_workf_version_4d8bb6_idx`：fields=['version', 'order'] condition=None

#### `WorkflowTransition`（表 `smass_workflow_workflowtransition`）

- 业务名称：流程转移
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `version` | ForeignKey → smass_workflow.WorkflowVersion on_delete=CASCADE | 否 | 否 | 版本 |
| `from_node` | ForeignKey → smass_workflow.WorkflowNode on_delete=CASCADE | 否 | 否 | 源节点 |
| `to_node` | ForeignKey → smass_workflow.WorkflowNode on_delete=CASCADE | 否 | 否 | 目标节点 |
| `action` | CharField max=32 | 否 | 否 | 动作 |

关系：

- `version` → `smass_workflow.WorkflowVersion`（related_name=`transitions`，on_delete=CASCADE）
- `from_node` → `smass_workflow.WorkflowNode`（related_name=`outgoing`，on_delete=CASCADE）
- `to_node` → `smass_workflow.WorkflowNode`（related_name=`incoming`，on_delete=CASCADE）

约束与索引：

- 约束 `r6_uniq_transition`（UniqueConstraint）：fields=['version', 'from_node', 'action'] condition=None
- 索引 `smass_workf_version_d89dbf_idx`：fields=['version', 'action'] condition=None

#### `WorkflowVersion`（表 `smass_workflow_workflowversion`）

- 业务名称：流程版本
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `definition` | ForeignKey → smass_workflow.WorkflowDefinition on_delete=CASCADE | 否 | 否 | 流程 |
| `version` | IntegerField | 否 | 否 | 版本号 |
| `status` | CharField max=16 choices=draft/active/archived | 否 | 否 | 状态 |
| `published_at` | DateTimeField null blank | 是 | 否 | 发布时间 |

关系：

- `definition` → `smass_workflow.WorkflowDefinition`（related_name=`versions`，on_delete=CASCADE）

约束与索引：

- 约束 `r6_uniq_version`（UniqueConstraint）：fields=['definition', 'version'] condition=None
- 索引 `smass_workf_definit_25d9ac_idx`：fields=['definition', 'status'] condition=None


---

## smass_analytics

### 指标与报表

指标定义、快照、报表定义/运行、数据质量问题。

#### `DataQualityIssue`（表 `smass_analytics_dataqualityissue`）

- 业务名称：数据质量问题
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=32 | 否 | 否 | 问题码 |
| `metric` | ForeignKey null blank → smass_analytics.MetricDefinition on_delete=SET_NULL | 是 | 否 | 指标 |
| `message` | CharField max=255 | 否 | 否 | 说明 |
| `severity` | CharField max=16 choices=info/warning | 否 | 否 | 级别 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `metric` → `smass_analytics.MetricDefinition`（related_name=`issues`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_analy_metric__30d954_idx`：fields=['metric', 'created_at'] condition=None

#### `MetricDefinition`（表 `smass_analytics_metricdefinition`）

- 业务名称：指标定义
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 指标编码 |
| `name` | CharField max=128 | 否 | 否 | 指标名称 |
| `description` | CharField max=255 blank | 否 | 否 | 口径说明 |
| `data_source` | CharField max=32 choices=organization/student/academic/workflow | 否 | 否 | 数据源 |
| `definition` | JSONField blank | 否 | 否 | 定义 |
| `period` | CharField max=32 | 否 | 否 | 统计周期 |
| `precision` | IntegerField | 否 | 否 | 小数位 |
| `owner` | CharField max=32 blank | 否 | 否 | 责任人 |
| `permission_roles` | JSONField blank | 否 | 否 | 可见角色 |
| `version` | IntegerField | 否 | 否 | 版本号 |
| `is_enabled` | BooleanField | 否 | 否 | 已启用 |
| `validated_at` | DateTimeField null blank | 是 | 否 | 校验时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_analy_data_so_f818c9_idx`：fields=['data_source', 'is_enabled'] condition=None

#### `MetricSnapshot`（表 `smass_analytics_metricsnapshot`）

- 业务名称：指标快照
- 主键：`id`
- 排序：未设置
- 敏感字段：`scope_hash`、`query_hash`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `metric` | ForeignKey → smass_analytics.MetricDefinition on_delete=CASCADE | 否 | 否 | 指标 |
| `metric_version` | IntegerField | 否 | 否 | 指标版本 |
| `value` | DecimalField | 否 | 否 | 数值 |
| `scope_hash` | CharField max=32 blank | 否 | 否 | 范围哈希 |
| `query_hash` | CharField max=32 blank | 否 | 否 | 查询哈希 |
| `computed_by` | CharField max=32 blank | 否 | 否 | 计算者 |
| `computed_at` | DateTimeField blank | 否 | 否 | 计算时间 |

关系：

- `metric` → `smass_analytics.MetricDefinition`（related_name=`snapshots`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_analy_metric__3b3a19_idx`：fields=['metric', 'computed_at'] condition=None
- 索引 `smass_analy_query_h_19fedb_idx`：fields=['query_hash'] condition=None

#### `ReportDefinition`（表 `smass_analytics_reportdefinition`）

- 业务名称：报表定义
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 报表编码 |
| `name` | CharField max=128 | 否 | 否 | 报表名称 |
| `permission_roles` | JSONField blank | 否 | 否 | 可见角色 |
| `is_enabled` | BooleanField | 否 | 否 | 已启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `metrics` | ManyToManyField blank → smass_analytics.MetricDefinition | 否 | 否 | 指标 |

关系：

- `metrics` → `smass_analytics.MetricDefinition`（related_name=`reports`，on_delete=—）

#### `ReportRun`（表 `smass_analytics_reportrun`）

- 业务名称：报表运行
- 主键：`id`
- 排序：未设置
- 敏感字段：`query_hash`、`scope_hash`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `report` | ForeignKey → smass_analytics.ReportDefinition on_delete=CASCADE | 否 | 否 | 报表 |
| `status` | CharField max=16 choices=ok/failed | 否 | 否 | 状态 |
| `row_count` | IntegerField | 否 | 否 | 行数 |
| `query_hash` | CharField max=32 blank | 否 | 否 | 查询哈希 |
| `scope_hash` | CharField max=32 blank | 否 | 否 | 范围哈希 |
| `rows` | JSONField blank | 否 | 否 | 结果行 |
| `ran_by` | CharField max=32 blank | 否 | 否 | 运行者 |
| `ran_at` | DateTimeField blank | 否 | 否 | 运行时间 |

关系：

- `report` → `smass_analytics.ReportDefinition`（related_name=`runs`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_analy_report__fe0165_idx`：fields=['report', 'ran_at'] condition=None


---

## smass_api

### 开放 API

API 客户端、令牌、幂等记录（开放接口）。

#### `ApiCallLog`（表 `smass_api_apicalllog`）

- 业务名称：API 调用日志
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account_name` | CharField max=64 blank | 否 | 否 | 服务账号 |
| `method` | CharField max=8 | 否 | 否 | 方法 |
| `path` | CharField max=255 | 否 | 否 | 路径 |
| `status_code` | IntegerField | 否 | 否 | 状态码 |
| `duration_ms` | IntegerField | 否 | 否 | 耗时毫秒 |
| `client_ip` | CharField max=45 blank | 否 | 否 | 来源 IP |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `smass_api_a_account_2817e8_idx`：fields=['account_name', 'created_at'] condition=None

#### `IdempotencyKey`（表 `smass_api_idempotencykey`）

- 业务名称：幂等键
- 主键：`id`
- 排序：未设置
- 敏感字段：`request_hash`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `key` | CharField max=64 unique | 否 | 是 | 幂等键 |
| `account_name` | CharField max=64 blank | 否 | 否 | 服务账号 |
| `request_hash` | CharField max=32 blank | 否 | 否 | 请求哈希 |
| `response_json` | JSONField blank | 否 | 否 | 首次响应 |
| `status_code` | IntegerField | 否 | 否 | 首次状态码 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_api_i_account_fe9c10_idx`：fields=['account_name', 'created_at'] condition=None

#### `ServiceAccount`（表 `smass_api_serviceaccount`）

- 业务名称：服务账号
- 主键：`id`
- 排序：未设置
- 敏感字段：`token_hash`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=64 unique | 否 | 是 | 名称 |
| `token_hash` | CharField max=64 unique | 否 | 是 | 令牌摘要 |
| `scopes` | JSONField blank | 否 | 否 | 权限范围 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `rate_limit_per_minute` | IntegerField | 否 | 否 | 每分钟限流 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_api_s_is_acti_3f7964_idx`：fields=['is_active'] condition=None

#### `SyncJob`（表 `smass_api_syncjob`）

- 业务名称：同步作业
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `job_id` | UUIDField max=32 unique | 否 | 是 | 作业号 |
| `connector` | CharField max=64 | 否 | 否 | 连接器 |
| `status` | CharField max=16 choices=pending/running/done/failed | 否 | 否 | 状态 |
| `payload` | JSONField blank | 否 | 否 | 输入 |
| `result` | JSONField blank | 否 | 否 | 结果 |
| `replay_detected` | BooleanField | 否 | 否 | 检出重放 |
| `compensated` | BooleanField | 否 | 否 | 已补偿 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `finished_at` | DateTimeField null blank | 是 | 否 | 完成时间 |

约束与索引：

- 索引 `smass_api_s_connect_4fb761_idx`：fields=['connector', 'status'] condition=None


---

## smass_operations

### 运维监控与告警

请求指标、告警规则/事件、就绪探针。

#### `AlertEvent`（表 `smass_operations_alertevent`）

- 业务名称：告警事件
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `rule` | ForeignKey → smass_operations.AlertRule on_delete=CASCADE | 否 | 否 | 规则 |
| `observed` | FloatField | 否 | 否 | 观测值 |
| `threshold` | FloatField | 否 | 否 | 阈值 |
| `severity` | CharField max=16 | 否 | 否 | 级别 |
| `detail` | CharField max=255 blank | 否 | 否 | 说明 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `rule` → `smass_operations.AlertRule`（related_name=`events`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_opera_rule_id_836779_idx`：fields=['rule', 'created_at'] condition=None

#### `AlertRule`（表 `smass_operations_alertrule`）

- 业务名称：告警规则
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 规则编码 |
| `name` | CharField max=128 | 否 | 否 | 名称 |
| `metric` | CharField max=32 choices=error_rate/latency_p95/db_errors | 否 | 否 | 指标 |
| `threshold` | FloatField | 否 | 否 | 阈值 |
| `window_seconds` | IntegerField | 否 | 否 | 窗口秒数 |
| `severity` | CharField max=16 choices=warning/critical | 否 | 否 | 级别 |
| `is_enabled` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_opera_is_enab_195665_idx`：fields=['is_enabled', 'metric'] condition=None

#### `ReadinessProbe`（表 `smass_operations_readinessprobe`）

- 业务名称：就绪探针
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=64 | 否 | 否 | 检查项 |
| `ok` | BooleanField | 否 | 否 | 通过 |
| `detail` | CharField max=255 blank | 否 | 否 | 详情 |
| `duration_ms` | IntegerField | 否 | 否 | 耗时毫秒 |
| `checked_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `smass_opera_name_465e53_idx`：fields=['name', 'checked_at'] condition=None

#### `RequestMetric`（表 `smass_operations_requestmetric`）

- 业务名称：请求指标
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `method` | CharField max=8 | 否 | 否 | 方法 |
| `route` | CharField max=200 | 否 | 否 | 路径 |
| `status_code` | IntegerField | 否 | 否 | 状态码 |
| `duration_ms` | IntegerField | 否 | 否 | 耗时毫秒 |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

约束与索引：

- 索引 `smass_opera_created_a59b5d_idx`：fields=['created_at', 'status_code'] condition=None
- 索引 `smass_opera_route_0db6b5_idx`：fields=['route', 'created_at'] condition=None


---

## smass_scheduling

### 排课与课表

节次、教师档案与约束、群体、排课运行、课时需求、课表条目与冲突解释。

#### `Cohort`（表 `smass_scheduling_cohort`）

- 业务名称：修读群体
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 群体编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `size` | IntegerField | 否 | 否 | 人数 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

#### `LessonRequirement`（表 `smass_scheduling_requirement`）

- 业务名称：课时需求
- 主键：`id`
- 排序：-priority、pk
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `run` | ForeignKey → smass_scheduling.ScheduleRun on_delete=CASCADE | 否 | 否 | 排课批次 |
| `section` | ForeignKey → smass_academic.TeachingSection on_delete=CASCADE | 否 | 否 | 教学班 |
| `teacher` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 主讲教师 |
| `cohort` | ForeignKey → smass_scheduling.Cohort on_delete=PROTECT | 否 | 否 | 修读群体 |
| `weekly_sessions` | IntegerField | 否 | 否 | 每周次数 |
| `session_periods` | IntegerField | 否 | 否 | 每次节数 |
| `students` | IntegerField | 否 | 否 | 学生数 |
| `required_room_type` | CharField max=16 blank | 否 | 否 | 要求教室类型 |
| `priority` | IntegerField | 否 | 否 | 优先级 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `run` → `smass_scheduling.ScheduleRun`（related_name=`requirements`，on_delete=CASCADE）
- `section` → `smass_academic.TeachingSection`（related_name=`scheduling_requirements`，on_delete=CASCADE）
- `teacher` → `r21_account.Account`（related_name=`scheduling_requirements`，on_delete=PROTECT）
- `cohort` → `smass_scheduling.Cohort`（related_name=`requirements`，on_delete=PROTECT）

约束与索引：

- 约束 `r11_uniq_run_section`（UniqueConstraint）：fields=['run', 'section'] condition=None
- 约束 `r11_weekly_sessions_positive`（CheckConstraint）：fields=[] condition=<Q: (AND: ('weekly_sessions__gte', 1))>
- 约束 `r11_session_periods_positive`（CheckConstraint）：fields=[] condition=<Q: (AND: ('session_periods__gte', 1))>

#### `ScheduleConflict`（表 `smass_scheduling_conflict`）

- 业务名称：排课冲突
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `run` | ForeignKey → smass_scheduling.ScheduleRun on_delete=CASCADE | 否 | 否 | 排课批次 |
| `requirement` | ForeignKey null blank → smass_scheduling.LessonRequirement on_delete=SET_NULL | 是 | 否 | 课时需求 |
| `kind` | CharField max=48 | 否 | 否 | 冲突类型 |
| `weekday` | IntegerField null blank | 是 | 否 | 星期 |
| `period` | IntegerField null blank | 是 | 否 | 节次 |
| `detail` | CharField max=255 blank | 否 | 否 | 说明 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `run` → `smass_scheduling.ScheduleRun`（related_name=`conflicts`，on_delete=CASCADE）
- `requirement` → `smass_scheduling.LessonRequirement`（related_name=`conflicts`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_sched_run_id_803818_idx`：fields=['run', 'kind'] condition=None

#### `ScheduleEntry`（表 `smass_scheduling_entry`）

- 业务名称：排课结果
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `run` | ForeignKey → smass_scheduling.ScheduleRun on_delete=CASCADE | 否 | 否 | 排课批次 |
| `requirement` | ForeignKey → smass_scheduling.LessonRequirement on_delete=CASCADE | 否 | 否 | 课时需求 |
| `room` | ForeignKey → smass_facilities.Room on_delete=PROTECT | 否 | 否 | 教室 |
| `teacher` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 教师 |
| `cohort` | ForeignKey → smass_scheduling.Cohort on_delete=PROTECT | 否 | 否 | 修读群体 |
| `weekday` | SmallIntegerField | 否 | 否 | 星期 |
| `period` | SmallIntegerField | 否 | 否 | 节次 |
| `session_index` | IntegerField | 否 | 否 | 第几次课 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `run` → `smass_scheduling.ScheduleRun`（related_name=`entries`，on_delete=CASCADE）
- `requirement` → `smass_scheduling.LessonRequirement`（related_name=`entries`，on_delete=CASCADE）
- `room` → `smass_facilities.Room`（related_name=`schedule_entries`，on_delete=PROTECT）
- `teacher` → `r21_account.Account`（related_name=`schedule_entries`，on_delete=PROTECT）
- `cohort` → `smass_scheduling.Cohort`（related_name=`schedule_entries`，on_delete=PROTECT）

约束与索引：

- 约束 `r11_uniq_room_slot`（UniqueConstraint）：fields=['run', 'room', 'weekday', 'period'] condition=None
- 约束 `r11_uniq_teacher_slot`（UniqueConstraint）：fields=['run', 'teacher', 'weekday', 'period'] condition=None
- 约束 `r11_uniq_cohort_slot`（UniqueConstraint）：fields=['run', 'cohort', 'weekday', 'period'] condition=None
- 约束 `r11_uniq_requirement_slot`（UniqueConstraint）：fields=['run', 'requirement', 'weekday', 'period'] condition=None
- 索引 `smass_sched_run_id_3ecdf7_idx`：fields=['run', 'weekday', 'period'] condition=None
- 索引 `smass_sched_run_id_c05ded_idx`：fields=['run', 'teacher'] condition=None
- 索引 `smass_sched_run_id_895e49_idx`：fields=['run', 'room'] condition=None

#### `ScheduleRun`（表 `smass_scheduling_run`）

- 业务名称：排课批次
- 主键：`id`
- 排序：-created_at
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `term` | ForeignKey → smass_academic.AcademicTerm on_delete=CASCADE | 否 | 否 | 学期 |
| `status` | CharField max=16 choices=draft/solved/infeasible/published/archived | 否 | 否 | 状态 |
| `algorithm` | CharField max=64 blank | 否 | 否 | 算法 |
| `seed` | IntegerField | 否 | 否 | 随机种子 |
| `hard_conflicts` | IntegerField | 否 | 否 | 硬冲突数 |
| `soft_cost` | IntegerField | 否 | 否 | 软成本 |
| `placed_sessions` | IntegerField | 否 | 否 | 已排节次 |
| `required_sessions` | IntegerField | 否 | 否 | 所需节次 |
| `explanation` | JSONField blank | 否 | 否 | 求解说明 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建者 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `published_at` | DateTimeField null blank | 是 | 否 | 发布时间 |

关系：

- `term` → `smass_academic.AcademicTerm`（related_name=`schedule_runs`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_sched_term_id_a5b4ce_idx`：fields=['term', 'status'] condition=None

#### `TeacherAvailability`（表 `smass_scheduling_availability`）

- 业务名称：教师可用时段
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 教师 |
| `weekday` | SmallIntegerField | 否 | 否 | 星期 |
| `period` | SmallIntegerField | 否 | 否 | 节次 |

关系：

- `account` → `r21_account.Account`（related_name=`scheduling_availability`，on_delete=CASCADE）

约束与索引：

- 约束 `r11_uniq_teacher_availability`（UniqueConstraint）：fields=['account', 'weekday', 'period'] condition=None
- 索引 `smass_sched_account_a9df6e_idx`：fields=['account', 'weekday'] condition=None

#### `TeacherConstraint`（表 `smass_scheduling_teacher_constraint`）

- 业务名称：教师特殊约束
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 教师 |
| `kind` | CharField max=16 choices=unavailable/prefer/avoid | 否 | 否 | 类型 |
| `weekday` | SmallIntegerField | 否 | 否 | 星期 |
| `period` | SmallIntegerField | 否 | 否 | 节次 |
| `reason` | CharField max=200 blank | 否 | 否 | 原因 |
| `approved_by` | CharField max=32 blank | 否 | 否 | 批准人 |
| `approved_at` | DateTimeField null blank | 是 | 否 | 批准时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `account` → `r21_account.Account`（related_name=`scheduling_constraints`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_sched_account_f6124f_idx`：fields=['account', 'kind'] condition=None

#### `TeacherProfile`（表 `smass_scheduling_teacher_profile`）

- 业务名称：教师排课属性
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | OneToOneField unique → r21_account.Account on_delete=CASCADE | 否 | 是 | 账号 |
| `instructor_type` | CharField max=24 choices=professor/associate_professor/lecturer/lab_teacher/admin_dual/visiting | 否 | 否 | 教师类型 |
| `weekly_hour_cap` | IntegerField | 否 | 否 | 周课时上限 |
| `max_daily_periods` | IntegerField | 否 | 否 | 单日最大节数 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `account` → `r21_account.Account`（related_name=`scheduling_profile`，on_delete=CASCADE）

#### `TimeSlot`（表 `smass_scheduling_timeslot`）

- 业务名称：时间槽
- 主键：`id`
- 排序：weekday、period
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `weekday` | SmallIntegerField | 否 | 否 | 星期 |
| `period` | SmallIntegerField | 否 | 否 | 节次 |
| `start_time` | TimeField | 否 | 否 | 开始时间 |
| `end_time` | TimeField | 否 | 否 | 结束时间 |
| `label` | CharField max=32 blank | 否 | 否 | 显示名 |

约束与索引：

- 约束 `r11_uniq_timeslot`（UniqueConstraint）：fields=['weekday', 'period'] condition=None
- 约束 `r11_period_positive`（CheckConstraint）：fields=[] condition=<Q: (AND: ('period__gte', 1))>
- 约束 `r11_weekday_range`（CheckConstraint）：fields=[] condition=<Q: (AND: ('weekday__gte', 0), ('weekday__lte', 6))>


---

## smass_enrollment

### 分班、转专业与学籍异动

自动分班规则/批次/结果、转专业申请、学籍状态变更。

#### `MajorTransferRequest`（表 `smass_enrollment_majortransferrequest`）

- 业务名称：转专业申请
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `from_unit` | ForeignKey null blank → smass_organization.OrganizationUnit on_delete=SET_NULL | 是 | 否 | 当前组织 |
| `to_major` | ForeignKey → smass_organization.OrganizationUnit on_delete=PROTECT | 否 | 否 | 目标专业 |
| `target_class` | ForeignKey null blank → smass_organization.OrganizationUnit on_delete=SET_NULL | 是 | 否 | 目标班级 |
| `reason` | CharField max=500 blank | 否 | 否 | 申请理由 |
| `status` | CharField max=16 choices=submitted/approved/rejected/effective/cancelled | 否 | 否 | 状态 |
| `submitted_by` | CharField max=32 blank | 否 | 否 | 提交人 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `effective_at` | DateTimeField null blank | 是 | 否 | 生效时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 提交时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`transfer_requests`，on_delete=PROTECT）
- `from_unit` → `smass_organization.OrganizationUnit`（related_name=`+`，on_delete=SET_NULL）
- `to_major` → `smass_organization.OrganizationUnit`（related_name=`+`，on_delete=PROTECT）
- `target_class` → `smass_organization.OrganizationUnit`（related_name=`+`，on_delete=SET_NULL）

约束与索引：

- 约束 `r12_uniq_active_transfer`（UniqueConstraint）：fields=['record'] condition=<Q: (AND: ('status__in', ['submitted', 'approved']))>
- 索引 `smass_enrol_status_a828c8_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_enrol_record__d6a5e1_idx`：fields=['record', 'status'] condition=None

#### `PlacementAssignment`（表 `smass_enrollment_placementassignment`）

- 业务名称：分班结果
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `batch` | ForeignKey → smass_enrollment.PlacementBatch on_delete=CASCADE | 否 | 否 | 批次 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `from_unit` | ForeignKey null blank → smass_organization.OrganizationUnit on_delete=SET_NULL | 是 | 否 | 原组织 |
| `to_unit` | ForeignKey → smass_organization.OrganizationUnit on_delete=PROTECT | 否 | 否 | 目标班级 |
| `status` | CharField max=16 choices=planned/applied/rolled_back | 否 | 否 | 状态 |

关系：

- `batch` → `smass_enrollment.PlacementBatch`（related_name=`assignments`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`placement_assignments`，on_delete=PROTECT）
- `from_unit` → `smass_organization.OrganizationUnit`（related_name=`+`，on_delete=SET_NULL）
- `to_unit` → `smass_organization.OrganizationUnit`（related_name=`+`，on_delete=PROTECT）

约束与索引：

- 约束 `r12_uniq_batch_record`（UniqueConstraint）：fields=['batch', 'record'] condition=None
- 索引 `smass_enrol_record__dd6c42_idx`：fields=['record', 'status'] condition=None

#### `PlacementBatch`（表 `smass_enrollment_placementbatch`）

- 业务名称：分班批次
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `rule` | ForeignKey → smass_enrollment.PlacementRule on_delete=PROTECT | 否 | 否 | 规则 |
| `status` | CharField max=16 choices=preview/applied/rolled_back | 否 | 否 | 状态 |
| `actor_id` | CharField max=32 blank | 否 | 否 | 操作者 |
| `stats` | JSONField blank | 否 | 否 | 统计 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `applied_at` | DateTimeField null blank | 是 | 否 | 执行时间 |
| `rolled_back_at` | DateTimeField null blank | 是 | 否 | 回滚时间 |

关系：

- `rule` → `smass_enrollment.PlacementRule`（related_name=`batches`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_enrol_status_011ee4_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_enrol_rule_id_48ad09_idx`：fields=['rule', 'status'] condition=None

#### `PlacementRule`（表 `smass_enrollment_placementrule`）

- 业务名称：分班规则
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `name` | CharField max=64 | 否 | 否 | 规则名称 |
| `major` | ForeignKey → smass_organization.OrganizationUnit on_delete=PROTECT | 否 | 否 | 专业 |
| `grade_label` | CharField max=32 blank | 否 | 否 | 年级标签 |
| `capacity_per_class` | PositiveIntegerField | 否 | 否 | 每班容量 |
| `strategy` | CharField max=16 choices=balanced/round_robin | 否 | 否 | 分配策略 |
| `balance_keys` | JSONField blank | 否 | 否 | 均衡维度 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `major` → `smass_organization.OrganizationUnit`（related_name=`placement_rules`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_enrol_major_i_f74a34_idx`：fields=['major', 'is_active'] condition=None

#### `StudentStatusChange`（表 `smass_enrollment_studentstatuschange`）

- 业务名称：学籍异动
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `change_type` | CharField max=16 choices=suspend/resume/withdraw/graduate/transfer_out | 否 | 否 | 异动类型 |
| `from_status` | CharField max=16 blank | 否 | 否 | 原学籍状态 |
| `to_status` | CharField max=16 blank | 否 | 否 | 目标学籍状态 |
| `effective_date` | DateField null blank | 是 | 否 | 生效日期 |
| `reason` | CharField max=500 blank | 否 | 否 | 原因 |
| `status` | CharField max=16 choices=submitted/approved/rejected/effective/cancelled | 否 | 否 | 状态 |
| `submitted_by` | CharField max=32 blank | 否 | 否 | 提交人 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `effective_at` | DateTimeField null blank | 是 | 否 | 生效时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 提交时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`status_changes`，on_delete=PROTECT）

约束与索引：

- 约束 `r12_uniq_active_status_change`（UniqueConstraint）：fields=['record'] condition=<Q: (AND: ('status__in', ['submitted', 'approved']))>
- 索引 `smass_enrol_status_b47fb2_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_enrol_record__d42815_idx`：fields=['record', 'status'] condition=None


---

## smass_attendance

### 考勤与请假

考勤场次、逐人考勤、请假、补签。

#### `AttendanceRecord`（表 `smass_attendance_attendancerecord`）

- 业务名称：考勤记录
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `session` | ForeignKey → smass_attendance.AttendanceSession on_delete=CASCADE | 否 | 否 | 考勤会话 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `status` | CharField max=16 choices=present/late/absent/leave | 否 | 否 | 考勤状态 |
| `source` | CharField max=16 choices=self/teacher/makeup | 否 | 否 | 来源 |
| `checked_at` | DateTimeField null blank | 是 | 否 | 签到时间 |
| `ip` | CharField max=64 blank | 否 | 否 | 来源 IP |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `session` → `smass_attendance.AttendanceSession`（related_name=`records`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`attendance_records`，on_delete=PROTECT）

约束与索引：

- 约束 `r13_uniq_session_record`（UniqueConstraint）：fields=['session', 'record'] condition=None
- 索引 `smass_atten_record__f53e9b_idx`：fields=['record', 'status'] condition=None
- 索引 `smass_atten_session_e747a7_idx`：fields=['session', 'status'] condition=None

#### `AttendanceSession`（表 `smass_attendance_attendancesession`）

- 业务名称：考勤会话
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `unit` | ForeignKey → smass_organization.OrganizationUnit on_delete=PROTECT | 否 | 否 | 班级 |
| `session_date` | DateField | 否 | 否 | 日期 |
| `period` | CharField max=16 | 否 | 否 | 节次 |
| `topic` | CharField max=100 blank | 否 | 否 | 考勤说明 |
| `status` | CharField max=16 choices=open/closed | 否 | 否 | 状态 |
| `code` | CharField max=8 blank | 否 | 否 | 签到码 |
| `code_expires_at` | DateTimeField null blank | 是 | 否 | 签到码过期时间 |
| `late_after_minutes` | PositiveSmallIntegerField | 否 | 否 | 迟到判定（分钟） |
| `created_by` | CharField max=32 blank | 否 | 否 | 发起人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `closed_at` | DateTimeField null blank | 是 | 否 | 关闭时间 |

关系：

- `unit` → `smass_organization.OrganizationUnit`（related_name=`attendance_sessions`，on_delete=PROTECT）

约束与索引：

- 约束 `r13_uniq_session_slot`（UniqueConstraint）：fields=['unit', 'session_date', 'period'] condition=None
- 索引 `smass_atten_unit_id_74e13c_idx`：fields=['unit', '-session_date'] condition=None
- 索引 `smass_atten_status_f58096_idx`：fields=['status', '-session_date'] condition=None

#### `LeaveRequest`（表 `smass_attendance_leaverequest`）

- 业务名称：请假申请
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `leave_type` | CharField max=16 choices=personal/sick/official | 否 | 否 | 类型 |
| `start_date` | DateField | 否 | 否 | 开始日期 |
| `end_date` | DateField | 否 | 否 | 结束日期 |
| `reason` | CharField max=500 blank | 否 | 否 | 事由 |
| `status` | CharField max=16 choices=submitted/approved/rejected/cancelled/closed | 否 | 否 | 状态 |
| `submitted_by` | CharField max=32 blank | 否 | 否 | 提交人 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `closed_at` | DateTimeField null blank | 是 | 否 | 销假时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 提交时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`leave_requests`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_atten_record__fb41c7_idx`：fields=['record', 'status'] condition=None
- 索引 `smass_atten_status_ca3625_idx`：fields=['status', '-created_at'] condition=None

#### `MakeupRequest`（表 `smass_attendance_makeuprequest`）

- 业务名称：补签申请
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `session` | ForeignKey → smass_attendance.AttendanceSession on_delete=PROTECT | 否 | 否 | 考勤会话 |
| `reason` | CharField max=500 | 否 | 否 | 补签理由 |
| `status` | CharField max=16 choices=submitted/approved/rejected | 否 | 否 | 状态 |
| `submitted_by` | CharField max=32 blank | 否 | 否 | 提交人 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `created_at` | DateTimeField blank | 否 | 否 | 提交时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`makeup_requests`，on_delete=PROTECT）
- `session` → `smass_attendance.AttendanceSession`（related_name=`makeup_requests`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_atten_record__a6133b_idx`：fields=['record', 'status'] condition=None
- 索引 `smass_atten_status_697dcb_idx`：fields=['status', '-created_at'] condition=None


---

## smass_activities

### 活动、志愿与学分

活动、报名、第二课堂学分与志愿时长认定。

#### `Activity`（表 `smass_activities_activity`）

- 业务名称：活动
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `title` | CharField max=100 | 否 | 否 | 活动名称 |
| `category` | CharField max=16 choices=second_class/volunteer/lecture/club | 否 | 否 | 类别 |
| `organizer` | ForeignKey null blank → r21_account.Account on_delete=SET_NULL | 是 | 否 | 组织者 |
| `location` | CharField max=100 blank | 否 | 否 | 地点 |
| `start_at` | DateTimeField | 否 | 否 | 开始时间 |
| `end_at` | DateTimeField | 否 | 否 | 结束时间 |
| `registration_deadline` | DateTimeField null blank | 是 | 否 | 报名截止 |
| `capacity` | PositiveIntegerField | 否 | 否 | 容量 |
| `credit_points` | DecimalField | 否 | 否 | 第二课堂学分 |
| `volunteer_hours` | DecimalField | 否 | 否 | 志愿时长（小时） |
| `status` | CharField max=16 choices=draft/published/closed/cancelled | 否 | 否 | 状态 |
| `checkin_code` | CharField max=8 blank | 否 | 否 | 签到码 |
| `checkin_expires_at` | DateTimeField null blank | 是 | 否 | 签到码过期时间 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `organizer` → `r21_account.Account`（related_name=`organized_activities`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_activ_status_35efd3_idx`：fields=['status', 'start_at'] condition=None
- 索引 `smass_activ_categor_3d4147_idx`：fields=['category', 'status'] condition=None

#### `ActivityCredit`（表 `smass_activities_activitycredit`）

- 业务名称：活动认定
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `activity` | ForeignKey → smass_activities.Activity on_delete=CASCADE | 否 | 否 | 活动 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `category` | CharField max=16 choices=second_class/volunteer/lecture/club | 否 | 否 | 类别 |
| `points` | DecimalField | 否 | 否 | 学分 |
| `hours` | DecimalField | 否 | 否 | 志愿时长 |
| `status` | CharField max=16 choices=pending/approved/rejected | 否 | 否 | 状态 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 认定人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 认定时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `activity` → `smass_activities.Activity`（related_name=`credits`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`activity_credits`，on_delete=PROTECT）

约束与索引：

- 约束 `r14_uniq_credit_activity_record`（UniqueConstraint）：fields=['activity', 'record'] condition=None
- 索引 `smass_activ_status_d84860_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_activ_record__c262e2_idx`：fields=['record', 'status'] condition=None

#### `ActivityRegistration`（表 `smass_activities_activityregistration`）

- 业务名称：活动报名
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `activity` | ForeignKey → smass_activities.Activity on_delete=CASCADE | 否 | 否 | 活动 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `status` | CharField max=16 choices=registered/waitlisted/cancelled/checked_in/absent | 否 | 否 | 状态 |
| `registered_at` | DateTimeField blank | 否 | 否 | 报名时间 |
| `checked_in_at` | DateTimeField null blank | 是 | 否 | 签到时间 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `activity` → `smass_activities.Activity`（related_name=`registrations`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`activity_registrations`，on_delete=PROTECT）

约束与索引：

- 约束 `r14_uniq_activity_record`（UniqueConstraint）：fields=['activity', 'record'] condition=None
- 索引 `smass_activ_activit_c22482_idx`：fields=['activity', 'status'] condition=None
- 索引 `smass_activ_record__c4e48f_idx`：fields=['record', 'status'] condition=None


---

## smass_clubs

### 社团与任职

社团、成员关系、社团职务任命。

#### `Club`（表 `smass_clubs_club`）

- 业务名称：群团组织
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `category` | CharField max=16 choices=league/student_union/club/association | 否 | 否 | 类别 |
| `parent` | ForeignKey null blank → smass_clubs.Club on_delete=PROTECT | 是 | 否 | 上级组织 |
| `advisor` | ForeignKey null blank → r21_account.Account on_delete=SET_NULL | 是 | 否 | 指导教师 |
| `description` | CharField max=500 blank | 否 | 否 | 简介 |
| `status` | CharField max=16 choices=active/archived | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `parent` → `smass_clubs.Club`（related_name=`children`，on_delete=PROTECT）
- `advisor` → `r21_account.Account`（related_name=`advised_clubs`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_clubs_categor_e71344_idx`：fields=['category', 'status'] condition=None
- 索引 `smass_clubs_parent__d89041_idx`：fields=['parent', 'status'] condition=None

#### `ClubMembership`（表 `smass_clubs_clubmembership`）

- 业务名称：组织成员
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `club` | ForeignKey → smass_clubs.Club on_delete=CASCADE | 否 | 否 | 组织 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `role` | CharField max=16 choices=member/leader | 否 | 否 | 成员角色 |
| `status` | CharField max=16 choices=pending/active/left/rejected | 否 | 否 | 状态 |
| `applied_at` | DateTimeField blank | 否 | 否 | 申请时间 |
| `joined_at` | DateTimeField null blank | 是 | 否 | 加入时间 |
| `left_at` | DateTimeField null blank | 是 | 否 | 退出时间 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |

关系：

- `club` → `smass_clubs.Club`（related_name=`memberships`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`club_memberships`，on_delete=PROTECT）

约束与索引：

- 约束 `r15_uniq_club_record`（UniqueConstraint）：fields=['club', 'record'] condition=None
- 索引 `smass_clubs_club_id_6a5f3d_idx`：fields=['club', 'status'] condition=None
- 索引 `smass_clubs_record__798e2b_idx`：fields=['record', 'status'] condition=None

#### `ClubPost`（表 `smass_clubs_clubpost`）

- 业务名称：干部任职
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `club` | ForeignKey → smass_clubs.Club on_delete=CASCADE | 否 | 否 | 组织 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `title` | CharField max=24 choices=president/vice_president/minister/secretary | 否 | 否 | 职务 |
| `term` | CharField max=32 | 否 | 否 | 任期 |
| `status` | CharField max=16 choices=active/ended | 否 | 否 | 状态 |
| `appointed_by` | CharField max=32 blank | 否 | 否 | 任命人 |
| `appointed_at` | DateTimeField blank | 否 | 否 | 任命时间 |
| `ended_at` | DateTimeField null blank | 是 | 否 | 卸任时间 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `club` → `smass_clubs.Club`（related_name=`posts`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`club_posts`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_clubs_club_id_572550_idx`：fields=['club', 'term', 'status'] condition=None
- 索引 `smass_clubs_record__6a70a4_idx`：fields=['record', 'status'] condition=None


---

## smass_facilities

### 场地与预约

楼宇、房间、设备、资格、可用时段、维护期、预约。

#### `Building`（表 `smass_facilities_building`）

- 业务名称：楼宇
- 主键：`id`
- 排序：未设置
- 敏感字段：`address`

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=32 unique | 否 | 是 | 楼宇编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `campus` | CharField max=64 blank | 否 | 否 | 校区 |
| `address` | CharField max=200 blank | 否 | 否 | 地址 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

约束与索引：

- 索引 `smass_facil_is_acti_04c1f6_idx`：fields=['is_active'] condition=None

#### `Equipment`（表 `smass_facilities_equipment`）

- 业务名称：设备
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=32 unique | 否 | 是 | 设备编码 |
| `name` | CharField max=64 | 否 | 否 | 名称 |
| `kind` | CharField max=32 blank | 否 | 否 | 类别 |
| `is_active` | BooleanField | 否 | 否 | 启用 |

#### `MaintenanceWindow`（表 `smass_facilities_maintenance`）

- 业务名称：维护封闭期
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `room` | ForeignKey → smass_facilities.Room on_delete=CASCADE | 否 | 否 | 房间 |
| `start_at` | DateTimeField | 否 | 否 | 开始 |
| `end_at` | DateTimeField | 否 | 否 | 结束 |
| `reason` | CharField max=200 blank | 否 | 否 | 原因 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建者 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `room` → `smass_facilities.Room`（related_name=`maintenances`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_facil_room_id_8e00f1_idx`：fields=['room', 'start_at'] condition=None

#### `Room`（表 `smass_facilities_room`）

- 业务名称：房间
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=32 unique | 否 | 是 | 房间编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `building` | ForeignKey → smass_facilities.Building on_delete=PROTECT | 否 | 否 | 楼宇 |
| `floor` | CharField max=16 blank | 否 | 否 | 楼层 |
| `room_type` | CharField max=16 choices=classroom/lab/study/meeting/other | 否 | 否 | 类型 |
| `capacity` | IntegerField | 否 | 否 | 容量 |
| `seat_count` | IntegerField | 否 | 否 | 座位数 |
| `status` | CharField max=16 choices=open/maintenance/closed | 否 | 否 | 状态 |
| `requires_qualification` | BooleanField | 否 | 否 | 需要资格 |
| `requires_approval` | BooleanField | 否 | 否 | 需要审批 |
| `is_active` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `building` → `smass_facilities.Building`（related_name=`rooms`，on_delete=PROTECT）

约束与索引：

- 约束 `r16_room_capacity_nonneg`（CheckConstraint）：fields=[] condition=<Q: (AND: ('capacity__gte', 0))>
- 约束 `r16_room_seat_nonneg`（CheckConstraint）：fields=[] condition=<Q: (AND: ('seat_count__gte', 0))>
- 索引 `smass_facil_buildin_149aa2_idx`：fields=['building', 'room_type'] condition=None
- 索引 `smass_facil_status_0a6ae8_idx`：fields=['status', 'is_active'] condition=None

#### `RoomAvailability`（表 `smass_facilities_availability`）

- 业务名称：可用时段
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `room` | ForeignKey → smass_facilities.Room on_delete=CASCADE | 否 | 否 | 房间 |
| `weekday` | SmallIntegerField | 否 | 否 | 星期 |
| `start_time` | TimeField | 否 | 否 | 开始时间 |
| `end_time` | TimeField | 否 | 否 | 结束时间 |

关系：

- `room` → `smass_facilities.Room`（related_name=`availabilities`，on_delete=CASCADE）

约束与索引：

- 约束 `r16_uniq_room_availability`（UniqueConstraint）：fields=['room', 'weekday', 'start_time', 'end_time'] condition=None
- 索引 `smass_facil_room_id_b52e99_idx`：fields=['room', 'weekday'] condition=None

#### `RoomBooking`（表 `smass_facilities_booking`）

- 业务名称：房间预约
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `room` | ForeignKey → smass_facilities.Room on_delete=PROTECT | 否 | 否 | 房间 |
| `account` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 申请人 |
| `purpose` | CharField max=200 | 否 | 否 | 用途 |
| `start_at` | DateTimeField | 否 | 否 | 开始 |
| `end_at` | DateTimeField | 否 | 否 | 结束 |
| `status` | CharField max=16 choices=pending/approved/checked_in/no_show/cancelled/released/rejected | 否 | 否 | 状态 |
| `attendees` | IntegerField | 否 | 否 | 人数 |
| `approved_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `approved_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `checked_in_at` | DateTimeField null blank | 是 | 否 | 签到时间 |
| `released_at` | DateTimeField null blank | 是 | 否 | 释放时间 |
| `cancel_reason` | CharField max=200 blank | 否 | 否 | 取消原因 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `room` → `smass_facilities.Room`（related_name=`bookings`，on_delete=PROTECT）
- `account` → `r21_account.Account`（related_name=`room_bookings`，on_delete=PROTECT）

约束与索引：

- 约束 `r16_booking_time_order`（CheckConstraint）：fields=[] condition=<Q: (AND: ('end_at__gt', F(start_at)))>
- 约束 `r16_booking_attendees_nonneg`（CheckConstraint）：fields=[] condition=<Q: (AND: ('attendees__gte', 0))>
- 索引 `smass_facil_room_id_0ab49e_idx`：fields=['room', 'start_at', 'end_at'] condition=None
- 索引 `smass_facil_account_0df454_idx`：fields=['account', 'start_at'] condition=None
- 索引 `smass_facil_status_dd97ec_idx`：fields=['status'] condition=None

#### `RoomEquipment`（表 `smass_facilities_room_equipment`）

- 业务名称：房间设备
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `room` | ForeignKey → smass_facilities.Room on_delete=CASCADE | 否 | 否 | 房间 |
| `equipment` | ForeignKey → smass_facilities.Equipment on_delete=CASCADE | 否 | 否 | 设备 |
| `quantity` | IntegerField | 否 | 否 | 数量 |

关系：

- `room` → `smass_facilities.Room`（related_name=`equipments`，on_delete=CASCADE）
- `equipment` → `smass_facilities.Equipment`（related_name=`默认`，on_delete=CASCADE）

约束与索引：

- 约束 `r16_uniq_room_equipment`（UniqueConstraint）：fields=['room', 'equipment'] condition=None
- 约束 `r16_room_equipment_nonneg`（CheckConstraint）：fields=[] condition=<Q: (AND: ('quantity__gte', 0))>

#### `RoomQualification`（表 `smass_facilities_qualification`）

- 业务名称：使用资格
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `room` | ForeignKey → smass_facilities.Room on_delete=CASCADE | 否 | 否 | 房间 |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 账号 |
| `granted_at` | DateTimeField blank | 否 | 否 | 授予时间 |
| `expires_at` | DateTimeField null blank | 是 | 否 | 到期时间 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `room` → `smass_facilities.Room`（related_name=`qualifications`，on_delete=CASCADE）
- `account` → `r21_account.Account`（related_name=`room_qualifications`，on_delete=CASCADE）

约束与索引：

- 约束 `r16_uniq_room_qualification`（UniqueConstraint）：fields=['room', 'account'] condition=None
- 索引 `smass_facil_account_f61f8c_idx`：fields=['account', 'room'] condition=None


---

## smass_forum

### 论坛、公告与举报

板块、帖子、评论、举报、公告。

#### `Announcement`（表 `smass_forum_announcement`）

- 业务名称：公告
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `title` | CharField max=120 | 否 | 否 | 标题 |
| `body` | TextField max=5000 | 否 | 否 | 正文 |
| `audience` | CharField max=16 choices=all/student/teacher | 否 | 否 | 受众 |
| `status` | CharField max=16 choices=draft/published | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `published_at` | DateTimeField null blank | 是 | 否 | 发布时间 |

约束与索引：

- 索引 `smass_forum_status_f254c7_idx`：fields=['status', '-published_at'] condition=None

#### `Board`（表 `smass_forum_board`）

- 业务名称：论坛板块
- 主键：`id`
- 排序：sort_order、code
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 编码 |
| `name` | CharField max=64 | 否 | 否 | 名称 |
| `description` | CharField max=200 blank | 否 | 否 | 简介 |
| `status` | CharField max=16 | 否 | 否 | 状态 |
| `sort_order` | IntegerField | 否 | 否 | 排序 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

#### `Comment`（表 `smass_forum_comment`）

- 业务名称：评论
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `post` | ForeignKey → smass_forum.Post on_delete=CASCADE | 否 | 否 | 帖子 |
| `author` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 作者 |
| `body` | CharField max=2000 | 否 | 否 | 内容 |
| `status` | CharField max=16 choices=published/hidden/removed | 否 | 否 | 状态 |
| `created_at` | DateTimeField blank | 否 | 否 | 发布时间 |

关系：

- `post` → `smass_forum.Post`（related_name=`comments`，on_delete=CASCADE）
- `author` → `r21_account.Account`（related_name=`forum_comments`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_forum_post_id_8f8f3c_idx`：fields=['post', 'status', 'created_at'] condition=None

#### `Post`（表 `smass_forum_post`）

- 业务名称：帖子
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `board` | ForeignKey → smass_forum.Board on_delete=PROTECT | 否 | 否 | 板块 |
| `author` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 作者 |
| `title` | CharField max=120 | 否 | 否 | 标题 |
| `body` | TextField max=5000 | 否 | 否 | 正文 |
| `status` | CharField max=16 choices=published/hidden/removed | 否 | 否 | 状态 |
| `pinned` | BooleanField | 否 | 否 | 置顶 |
| `view_count` | PositiveIntegerField | 否 | 否 | 浏览数 |
| `created_at` | DateTimeField blank | 否 | 否 | 发布时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `board` → `smass_forum.Board`（related_name=`posts`，on_delete=PROTECT）
- `author` → `r21_account.Account`（related_name=`forum_posts`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_forum_board_i_c3e07f_idx`：fields=['board', 'status', '-created_at'] condition=None
- 索引 `smass_forum_author__b01f0e_idx`：fields=['author', 'status'] condition=None

#### `Report`（表 `smass_forum_report`）

- 业务名称：举报
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `target_type` | CharField max=16 choices=post/comment | 否 | 否 | 对象类型 |
| `target_id` | PositiveIntegerField | 否 | 否 | 对象 ID |
| `reporter` | ForeignKey → r21_account.Account on_delete=PROTECT | 否 | 否 | 举报人 |
| `reason` | CharField max=500 | 否 | 否 | 举报理由 |
| `status` | CharField max=16 choices=pending/resolved/dismissed | 否 | 否 | 状态 |
| `action` | CharField max=16 blank | 否 | 否 | 处理动作 |
| `handled_by` | CharField max=32 blank | 否 | 否 | 处理人 |
| `handled_at` | DateTimeField null blank | 是 | 否 | 处理时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 举报时间 |

关系：

- `reporter` → `r21_account.Account`（related_name=`forum_reports`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_forum_status_dde641_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_forum_target__f366e6_idx`：fields=['target_type', 'target_id'] condition=None


---

## smass_finance

### 账单、缴费与退费

收费项目、账单、缴费、退费申请、台账。

#### `Bill`（表 `smass_finance_bill`）

- 业务名称：账单
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `bill_no` | CharField max=64 unique | 否 | 是 | 账单号 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `term` | CharField max=32 blank | 否 | 否 | 学年学期 |
| `total` | DecimalField | 否 | 否 | 应缴金额 |
| `paid` | DecimalField | 否 | 否 | 已缴金额 |
| `status` | CharField max=16 choices=unpaid/partial/paid/refunded/void | 否 | 否 | 状态 |
| `due_date` | DateField null blank | 是 | 否 | 缴费截止 |
| `created_at` | DateTimeField blank | 否 | 否 | 生成时间 |
| `updated_at` | DateTimeField blank | 否 | 否 | 更新时间 |

关系：

- `record` → `smass_organization.StudentRecord`（related_name=`finance_bills`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_finan_record__f2da91_idx`：fields=['record', 'status'] condition=None
- 索引 `smass_finan_term_4c532c_idx`：fields=['term', 'status'] condition=None

#### `BillItem`（表 `smass_finance_billitem`）

- 业务名称：账单明细
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `bill` | ForeignKey → smass_finance.Bill on_delete=CASCADE | 否 | 否 | 账单 |
| `fee_item` | ForeignKey → smass_finance.FeeItem on_delete=PROTECT | 否 | 否 | 收费项目 |
| `amount` | DecimalField | 否 | 否 | 金额 |

关系：

- `bill` → `smass_finance.Bill`（related_name=`items`，on_delete=CASCADE）
- `fee_item` → `smass_finance.FeeItem`（related_name=`bill_items`，on_delete=PROTECT）

约束与索引：

- 约束 `r18_uniq_bill_fee`（UniqueConstraint）：fields=['bill', 'fee_item'] condition=None

#### `FeeItem`（表 `smass_finance_feeitem`）

- 业务名称：收费项目
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 项目编码 |
| `name` | CharField max=100 | 否 | 否 | 项目名称 |
| `category` | CharField max=24 choices=tuition/accommodation/textbook/other | 否 | 否 | 类别 |
| `amount` | DecimalField | 否 | 否 | 金额 |
| `term` | CharField max=32 blank | 否 | 否 | 学年学期 |
| `status` | CharField max=16 | 否 | 否 | 状态 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_finan_term_0506ed_idx`：fields=['term', 'status'] condition=None

#### `LedgerEntry`（表 `smass_finance_ledgerentry`）

- 业务名称：财务台账
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `entry_no` | CharField max=64 unique | 否 | 是 | 流水号 |
| `entry_type` | CharField max=16 choices=charge/payment/refund/adjust | 否 | 否 | 类型 |
| `bill` | ForeignKey null blank → smass_finance.Bill on_delete=PROTECT | 是 | 否 | 账单 |
| `amount` | DecimalField | 否 | 否 | 金额 |
| `direction` | SmallIntegerField | 否 | 否 | 方向（+1 收 / -1 退） |
| `operator` | CharField max=32 blank | 否 | 否 | 经办人 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |
| `created_at` | DateTimeField blank | 否 | 否 | 记账时间 |

关系：

- `bill` → `smass_finance.Bill`（related_name=`ledger_entries`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_finan_created_668c0e_idx`：fields=['-created_at'] condition=None
- 索引 `smass_finan_entry_t_a1f035_idx`：fields=['entry_type', '-created_at'] condition=None

#### `Payment`（表 `smass_finance_payment`）

- 业务名称：缴费记录
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `bill` | ForeignKey → smass_finance.Bill on_delete=PROTECT | 否 | 否 | 账单 |
| `amount` | DecimalField | 否 | 否 | 金额 |
| `method` | CharField max=24 choices=synthetic_bank/synthetic_cash | 否 | 否 | 方式 |
| `status` | CharField max=16 choices=success/failed/refunded | 否 | 否 | 状态 |
| `reference` | CharField max=64 unique | 否 | 是 | 幂等键 |
| `operator` | CharField max=32 blank | 否 | 否 | 经办人 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |
| `created_at` | DateTimeField blank | 否 | 否 | 缴费时间 |

关系：

- `bill` → `smass_finance.Bill`（related_name=`payments`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_finan_bill_id_04cb92_idx`：fields=['bill', 'status'] condition=None

#### `RefundRequest`（表 `smass_finance_refundrequest`）

- 业务名称：退费申请
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `bill` | ForeignKey → smass_finance.Bill on_delete=PROTECT | 否 | 否 | 账单 |
| `amount` | DecimalField | 否 | 否 | 退费金额 |
| `reason` | CharField max=500 | 否 | 否 | 退费事由 |
| `status` | CharField max=16 choices=submitted/approved/rejected/paid | 否 | 否 | 状态 |
| `submitted_by` | CharField max=32 blank | 否 | 否 | 申请人 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `paid_by` | CharField max=32 blank | 否 | 否 | 出纳 |
| `paid_at` | DateTimeField null blank | 是 | 否 | 退费时间 |
| `created_at` | DateTimeField blank | 否 | 否 | 申请时间 |

关系：

- `bill` → `smass_finance.Bill`（related_name=`refunds`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_finan_status_b0417d_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_finan_bill_id_f67e0b_idx`：fields=['bill', 'status'] condition=None


---

## smass_party

### 党建与专项组织

党建/专项组织、成员、活动、文档、访问授权与访问日志。

#### `AccessGrant`（表 `smass_party_accessgrant`）

- 业务名称：资料访问授权
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 账号 |
| `level` | CharField max=16 choices=normal/sensitive | 否 | 否 | 级别 |
| `granted_by` | CharField max=32 blank | 否 | 否 | 授予人 |
| `granted_at` | DateTimeField blank | 否 | 否 | 授予时间 |
| `expires_at` | DateTimeField null blank | 是 | 否 | 到期时间 |
| `revoked_at` | DateTimeField null blank | 是 | 否 | 撤销时间 |

关系：

- `account` → `r21_account.Account`（related_name=`party_grants`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_party_account_4cf1ef_idx`：fields=['account', 'level', 'revoked_at'] condition=None

#### `AccessLog`（表 `smass_party_accesslog`）

- 业务名称：资料访问审计
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `account` | ForeignKey null blank → r21_account.Account on_delete=SET_NULL | 是 | 否 | 账号 |
| `account_id_text` | CharField max=32 blank | 否 | 否 | 账号标识 |
| `document` | ForeignKey null blank → smass_party.PartyDocument on_delete=SET_NULL | 是 | 否 | 资料 |
| `action` | CharField max=16 choices=view/request/approve/reject/deny | 否 | 否 | 动作 |
| `purpose` | CharField max=200 blank | 否 | 否 | 用途/说明 |
| `ip` | CharField max=64 blank | 否 | 否 | 来源 IP |
| `created_at` | DateTimeField blank | 否 | 否 | 时间 |

关系：

- `account` → `r21_account.Account`（related_name=`party_access_logs`，on_delete=SET_NULL）
- `document` → `smass_party.PartyDocument`（related_name=`access_logs`，on_delete=SET_NULL）

约束与索引：

- 索引 `smass_party_created_b7bcf1_idx`：fields=['-created_at'] condition=None
- 索引 `smass_party_documen_93768f_idx`：fields=['document', '-created_at'] condition=None

#### `AccessRequest`（表 `smass_party_accessrequest`）

- 业务名称：资料借阅申请
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `document` | ForeignKey → smass_party.PartyDocument on_delete=CASCADE | 否 | 否 | 资料 |
| `applicant` | ForeignKey → r21_account.Account on_delete=CASCADE | 否 | 否 | 申请人 |
| `purpose` | CharField max=500 | 否 | 否 | 用途 |
| `status` | CharField max=16 choices=submitted/approved/rejected/expired | 否 | 否 | 状态 |
| `reviewed_by` | CharField max=32 blank | 否 | 否 | 审批人 |
| `reviewed_at` | DateTimeField null blank | 是 | 否 | 审批时间 |
| `reject_reason` | CharField max=255 blank | 否 | 否 | 驳回原因 |
| `valid_until` | DateTimeField null blank | 是 | 否 | 有效期至 |
| `created_at` | DateTimeField blank | 否 | 否 | 申请时间 |

关系：

- `document` → `smass_party.PartyDocument`（related_name=`access_requests`，on_delete=CASCADE）
- `applicant` → `r21_account.Account`（related_name=`party_access_requests`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_party_status_7bbf3c_idx`：fields=['status', '-created_at'] condition=None
- 索引 `smass_party_applica_50018e_idx`：fields=['applicant', 'status'] condition=None

#### `PartyActivity`（表 `smass_party_partyactivity`）

- 业务名称：组织生活/专项活动
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `org` | ForeignKey → smass_party.PartyOrg on_delete=CASCADE | 否 | 否 | 组织 |
| `title` | CharField max=120 | 否 | 否 | 主题 |
| `activity_type` | CharField max=24 choices=meeting/theme_party_day/volunteer/training | 否 | 否 | 类型 |
| `held_on` | DateField | 否 | 否 | 开展日期 |
| `summary` | CharField max=500 blank | 否 | 否 | 纪要摘要（合成） |
| `status` | CharField max=16 choices=planned/done/cancelled | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `org` → `smass_party.PartyOrg`（related_name=`activities`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_party_org_id_476182_idx`：fields=['org', '-held_on'] condition=None

#### `PartyDocument`（表 `smass_party_partydocument`）

- 业务名称：受控资料
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `org` | ForeignKey → smass_party.PartyOrg on_delete=CASCADE | 否 | 否 | 组织 |
| `title` | CharField max=120 | 否 | 否 | 标题 |
| `classification` | CharField max=16 choices=public/internal/sensitive | 否 | 否 | 密级 |
| `summary` | CharField max=500 blank | 否 | 否 | 摘要（合成，不含真实材料） |
| `status` | CharField max=16 choices=draft/published/archived | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `org` → `smass_party.PartyOrg`（related_name=`documents`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_party_org_id_a8f118_idx`：fields=['org', 'classification'] condition=None

#### `PartyMember`（表 `smass_party_partymember`）

- 业务名称：组织成员
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `org` | ForeignKey → smass_party.PartyOrg on_delete=CASCADE | 否 | 否 | 组织 |
| `record` | ForeignKey → smass_organization.StudentRecord on_delete=PROTECT | 否 | 否 | 学籍档案 |
| `political_status` | CharField max=24 choices=party_member/league_member/activist/masses | 否 | 否 | 政治面貌 |
| `joined_at` | DateField null blank | 是 | 否 | 加入日期 |
| `status` | CharField max=16 | 否 | 否 | 状态 |
| `note` | CharField max=200 blank | 否 | 否 | 备注 |

关系：

- `org` → `smass_party.PartyOrg`（related_name=`members`，on_delete=CASCADE）
- `record` → `smass_organization.StudentRecord`（related_name=`party_memberships`，on_delete=PROTECT）

约束与索引：

- 约束 `r19_uniq_org_record`（UniqueConstraint）：fields=['org', 'record'] condition=None
- 索引 `smass_party_org_id_4ab938_idx`：fields=['org', 'status'] condition=None

#### `PartyOrg`（表 `smass_party_partyorg`）

- 业务名称：党建/专项组织
- 主键：`id`
- 排序：未设置
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 编码 |
| `name` | CharField max=100 | 否 | 否 | 名称 |
| `org_type` | CharField max=16 choices=branch/committee/special | 否 | 否 | 类型 |
| `parent` | ForeignKey null blank → smass_party.PartyOrg on_delete=PROTECT | 是 | 否 | 上级组织 |
| `sensitivity` | CharField max=16 choices=normal/sensitive | 否 | 否 | 敏感级别 |
| `status` | CharField max=16 | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

关系：

- `parent` → `smass_party.PartyOrg`（related_name=`children`，on_delete=PROTECT）

约束与索引：

- 索引 `smass_party_org_typ_2d9936_idx`：fields=['org_type', 'status'] condition=None
- 索引 `smass_party_parent__fcbd98_idx`：fields=['parent', 'status'] condition=None


---

## smass_portal

### 门户配置

门户分区、链接与门户公告（配置型）。

#### `PortalLink`（表 `smass_portal_portallink`）

- 业务名称：门户链接
- 主键：`id`
- 排序：sort_order、id
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `section` | ForeignKey → smass_portal.PortalSection on_delete=CASCADE | 否 | 否 | 区块 |
| `label` | CharField max=64 | 否 | 否 | 链接文字 |
| `url_name` | CharField max=120 blank | 否 | 否 | Django URL 名 |
| `fallback_url` | CharField max=200 blank | 否 | 否 | 备用地址 |
| `roles` | CharField max=120 | 否 | 否 | 可见角色（逗号分隔） |
| `sort_order` | IntegerField | 否 | 否 | 排序 |
| `enabled` | BooleanField | 否 | 否 | 启用 |

关系：

- `section` → `smass_portal.PortalSection`（related_name=`links`，on_delete=CASCADE）

约束与索引：

- 索引 `smass_porta_section_292c9f_idx`：fields=['section', 'enabled', 'sort_order'] condition=None

#### `PortalNotice`（表 `smass_portal_portalnotice`）

- 业务名称：门户公告
- 主键：`id`
- 排序：-published_at、-created_at
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `title` | CharField max=120 | 否 | 否 | 标题 |
| `body` | CharField max=1000 | 否 | 否 | 内容 |
| `roles` | CharField max=120 | 否 | 否 | 可见角色（逗号分隔） |
| `status` | CharField max=16 choices=draft/published | 否 | 否 | 状态 |
| `created_by` | CharField max=32 blank | 否 | 否 | 创建人 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |
| `published_at` | DateTimeField null blank | 是 | 否 | 发布时间 |

约束与索引：

- 索引 `smass_porta_status_473872_idx`：fields=['status', '-published_at'] condition=None

#### `PortalSection`（表 `smass_portal_portalsection`）

- 业务名称：门户区块
- 主键：`id`
- 排序：sort_order、code
- 敏感字段：无

| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |
|---|---|---|---|---|
| `id` | BigAutoField blank unique | 否 | 是 | ID |
| `code` | CharField max=64 unique | 否 | 是 | 编码 |
| `title` | CharField max=64 | 否 | 否 | 标题 |
| `subtitle` | CharField max=120 blank | 否 | 否 | 副标题 |
| `roles` | CharField max=120 | 否 | 否 | 可见角色（逗号分隔） |
| `sort_order` | IntegerField | 否 | 否 | 排序 |
| `enabled` | BooleanField | 否 | 否 | 启用 |
| `created_at` | DateTimeField blank | 否 | 否 | 创建时间 |

约束与索引：

- 索引 `smass_porta_enabled_3ef0fa_idx`：fields=['enabled', 'sort_order'] condition=None

---

## 自动生成的 M2M 中间表

以下表由 Django 自动创建，不单独出现在业务代码中：

| App | 模型 | 表 |
|---|---|---|
| auth | Group_permissions | auth_group_permissions |
| auth | User_groups | auth_user_groups |
| auth | User_user_permissions | auth_user_user_permissions |
| r21_account | Account_groups | r21_account_account_groups |
| r21_account | Account_user_permissions | r21_account_account_user_permissions |
| smass_analytics | ReportDefinition_metrics | smass_analytics_reportdefinition_metrics |

## Django 内置模型（6 个有效模型）

产品未改写 `AUTH_USER_MODEL`，以下内置表随 Django 迁移创建；产品路径只间接使用其中部分。

| App | 模型 | 表 | 用途 | 产品是否使用 | 敏感 |
|---|---|---|---|---|---|
| `auth` | `User` | `auth_user` | Django 默认用户（产品中为空置） | 否（认证走 `r21_account.Account`） | 密码哈希 |
| `auth` | `Group` | `auth_group` | 角色权限组（`r21_*` 组） | 是（`sync_account_groups`） | 否 |
| `auth` | `Permission` | `auth_permission` | 动作 codename | 是（RBAC 判定） | 否 |
| `contenttypes` | `ContentType` | `django_content_type` | 权限绑定模型 | 是（间接） | 否 |
| `sessions` | `Session` | `django_session` | 登录会话 | 是 | 会话键 |
| `admin` | `LogEntry` | `django_admin_log` | Django 后台操作日志 | 否（未挂载 admin 站点） | 否 |

> 统计：项目有效模型 114 + 内置 6 = 120；自动 M2M 中间表 6 个（见上节）。


## 数据关系（文字 ER）

- `r21_account.Account` 1:1 `StudentProfile` / `TeacherProfile`；
- `Account` 1:N `StudentRecord`（学籍档案）、`Enrollment`（选课）、`TeachingAssignment`（任课）、`RoomBooking`（预约）、`Notification`（通知）；
- `OrganizationUnit` 自关联树（学院→专业/年级→班级；部门自嵌套）；
- `StudentRecord` N:1 `OrganizationUnit`；1:N `AttendanceRecord`、`LeaveRequest`、`ActivityRegistration`、`ActivityCredit`、`ClubMembership`、`Bill`；
- `AcademicTerm` N:1 `AcademicYear`；`TeachingSection` N:1 `AcademicTerm`+`Course`；`Enrollment` N:1 `TeachingSection`+`Account`；
- `ScheduleRun` 1:N `LessonRequirement`/`ScheduleEntry`/`ScheduleConflict`；`ScheduleEntry` N:1 `Room`/`Teacher`/`Cohort`；
- `RoomBooking` N:1 `Room`+`Account`；`Bill` 1:N `BillItem`/`Payment`/`RefundRequest`；
- `WorkflowInstance` 1:N `WorkflowEvent`/`ApprovalTask`；`Notification` 独立按 `recipient` 字符串关联登录名。
