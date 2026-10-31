# 00 架构与目标 Schema

> 审计/重构基线：Git `0a5a26e`（产品代码 `80c8d85`）
> 工作区：`E:\PythonWeb\smass\.local\clean-dev`
> 产品配置：`smass.settings_product`（库 `smass_product_dev`）
> 统一验证配置：`smass.settings_unified_verify`（库 `smass_unified_verify`）
> 正式库：`smass`（**只读**，26 表）
> 日期：2026-10-31

---

## 1. 安全基线（实测）

| 项 | 实测值 | 校验方式 |
|---|---|---|
| Git HEAD | `0a5a26e2351b9b7961fecc33e59b00c12fece8f6` | `git rev-parse HEAD` |
| 产品库实际连接 | `smass_product_dev` @3306 | `SELECT DATABASE()` |
| 产品库表数 | 127 | `information_schema.tables` |
| 正式库 | `smass`，26 表 | 只读连接 + `SET SESSION TRANSACTION READ ONLY` |
| 正式库 app01 业务表 | 16 张（其中 4 张空：building/dormitory/dormitorynumber/nation） | 逐表 `COUNT(*)` |
| 正式库行数 | student 3 / teacher 2 / admin 1 / college 2 / major 3 / grade 3 / classes 2 / department 2 / classcommittee 1 / leaguecadres 1 / position 4 / teacherposition 2 | 只读统计 |
| 产品库 app01_* 表 | 18 张，**全部 0 行** | 逐表统计 |
| 产品库账号/学籍 | Account 15 / StudentRecord 7 / StudentProfile 7 / TeacherProfile 5 / OrganizationUnit 19 | ORM |
| 迁移文件 | 36 个（不含 `__init__`） | 扫描 |
| Git 备份 | 2 个 bundle + 3 个 tar.gz + SHA-256 清单（`.local/git-backups/protected/`） | 文件清点 |
| 数据库级加密备份 | **未发现** | `.local` 下无 `*.sql`/`*.dump`（仅演练用 s22_backup.sql） |

**硬约束**：

- 本轮所有脚本对正式库只建立只读连接，执行前后比对指纹
  （`940a687d…`），实测未变；
- 任何写操作的目标库必须命中 `smass_product_dev` 或
  `smass_unified_verify` 前缀，且从 Django `settings.DATABASES` 读取实际库名
  （不依赖环境变量名称推断）；
- 不执行 DROP/TRUNCATE/DELETE 正式库。

---

## 2. 目标架构

```
                    ┌──────────────────────────────────────┐
                    │  唯一权威业务数据库（目标）            │
                    │  Django 新模型 + 迁移历史              │
                    │  当前验证副本：smass_unified_verify    │
                    └───────────────┬──────────────────────┘
                                    │ 唯一读写
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
        ┌─────▼─────┐         ┌─────▼─────┐         ┌─────▼─────┐
        │ 学生工作台 │         │ 教师工作台 │         │ 管理控制台 │
        └─────┬─────┘         └─────┬─────┘         └─────┬─────┘
              └─────────────────────┼─────────────────────┘
                              ┌─────▼─────┐
                              │ smass_workspace │
                              │ 守卫/聚合/视图  │
                              └─────┬─────┘
        ┌───────────────┬───────────┼───────────┬───────────────┐
   r21_account   smass_organization  smass_academic  smass_attendance
   （身份）       （组织/学籍）        （教务）        （考勤）
        └───────────────┴───────────┼───────────┴───────────────┘
                          （其余业务模块：排课/选课/场地/活动/社团/
                            财务/公告/流程/分析/运维）

  ┌──────────────────── 一次性迁移层（非运行时） ────────────────────┐
  │ 正式库 smass（只读） → scripts/legacy_migration.py → 统一库        │
  │ app01 旧表只在迁移工具与兼容测试中保留                              │
  └────────────────────────────────────────────────────────────────┘
```

**目标**：上图"一次性迁移层"完成后，正式库不再出现在产品运行链路；
产品只连接唯一权威库。本轮已在隔离验证库完成该形态的验证。

---

## 3. 目标 Schema 原则

| 领域 | 唯一权威源 | 兼容/派生 | 说明 |
|---|---|---|---|
| 登录身份 | `r21_account.Account` | — | `auth.User` 保留但空置 |
| 角色 | `AccountRole` + Django Group | — | 4 个角色编码 |
| 学生学籍 | `smass_organization.StudentRecord` | `r21_account.StudentProfile` | 学号/姓名/组织/状态以 Record 为准；Profile 为兼容档案 |
| 教师档案 | `r21_account.TeacherProfile` | `app01.Teacher`（仅迁移源） | 工号/姓名/学院 |
| 任课 | `smass_academic.TeachingAssignment` | — | 账号 × 教学班 |
| 组织 | `smass_organization.OrganizationUnit` | app01 College/Major/Grade/Classes/Department | 单亲树 |
| 住宿 | `StudentRecord.extra.dormitory`（当前） | app01 Building/Dormitory/Number | 未来可建独立住宿分配表 |
| 任职 | `OrganizationMembership(role=...)` | app01 ClassCommittee/LeagueCadres | 班委/团学/辅导员 |
| 课程教学 | `AcademicYear/Term/Course/TeachingSection` | — | |
| 选课 | `Enrollment` + `EnrollmentHistory` | — | |
| 排课 | `ScheduleRun/Entry/Conflict` | — | 周模板 |
| 考勤请假 | `AttendanceSession/Record/LeaveRequest/MakeupRequest` | — | |
| 审批 | `WorkflowDefinition/Instance/Task/Event` + 各业务状态 | — | 请假用自身状态机 |
| 场地 | `Building/Room/RoomBooking` | — | |
| 活动社团 | `Activity/Registration/Credit`、`Club/Membership/Post` | — | |
| 财务 | `FeeItem/Bill/Payment/RefundRequest/LedgerEntry` | — | 不接真实支付 |
| 公告通知 | `Announcement/Notification` | — | |
| 审计 | `AccountAuditLog/LoginAttempt/WorkflowEvent/AccessLog/LedgerEntry/StudentRecordChange` | `r22.AccountAuditEvent`（兼容审计） | 追加式 |

### 3.1 重复模型的处置决策

| 重复项 | 决策 | 理由 |
|---|---|---|
| `StudentProfile` vs `StudentRecord` | **Record 为权威**；Profile 保留为"账号档案"（学号/姓名/学院/班级/掩码手机），迁移脚本同时写两处，产品页面优先读 Record；新增一致性校验 | 删除 Profile 会影响 r21 测试、登录展示与既有迁移；保留但明确派生关系 |
| `TeacherProfile` vs `app01.Teacher` | Profile 为权威；app01 仅迁移源 | app01 表不进产品运行链路 |
| `Account` vs `auth.User` | 保持 `AUTH_USER_MODEL` 为默认，认证走 Account | 切换自定义用户模型需重建 auth 表、重写 1800 例夹具，风险高；见 §4 |
| `OrganizationUnit` vs app01 组织表 | Unit 为权威；app01 归档 | 迁移已建立映射 |
| 住宿：`extra.dormitory` vs app01 住宿表 | extra 为当前权威；app01 归档 | 源数据住宿字段为空（实测 0 条有值），未来建议独立表 |

### 3.2 目标 Schema 的演进建议（本轮不实施）

1. **住宿独立表**：`DormitoryBuilding`、`DormitoryRoom`、`BedAssignment(student, bed, from, to)`，
   替代 `extra.dormitory` 的弱结构；迁移时从 extra 回填。
2. **任职统一表**：`OrganizationAppointment(account, unit, title, term, status)`，
   合并班委/团学/社团职务；`OrganizationMembership` 保留成员关系。
3. **教师档案并入 Account 或独立 TeacherRecord**：消除 `TeacherProfile` 与 app01 双份。
4. **通知 recipient 改 FK**：`Notification.recipient` → `Account`，解决改名/删号孤立。
5. **课表周次**：`ScheduleEntry.week_from/week_to` 或 `ScheduleEntryDate`。

> 以上均需独立迁移窗口与回滚验证，不在本轮授权范围。

---

## 4. 认证架构评估（是否切换 AUTH_USER_MODEL）

| 方案 | 影响 | 结论 |
|---|---|---|
| A. 保持默认 `auth.User` + 自定义 `Account`（现状） | 无迁移风险；`auth_user` 空置；Django 权限框架仍可用 | **推荐** |
| B. 切换 `AUTH_USER_MODEL='r21_account.Account'` | 需重建 auth 相关表与全部 FK、重写 1800 例夹具、数据迁移与回滚演练 | 本轮不实施；需单独可行性评审 |

本轮验证库按方案 A 建库（与产品一致），未改动 `AUTH_USER_MODEL`。

---

## 5. 数据库分层与用途

| 库 | 用途 | 本轮操作 |
|---|---|---|
| `smass` | 正式库（历史 app01） | 只读；迁移源；指纹前后一致 |
| `smass_product_dev` | 产品开发库（演示 + 迁移验证） | 只读检查；未重建 |
| `smass_unified_verify` | **新建统一验证库** | 建库、迁移、seed、迁移演练、断库测试、回滚重迁 |
| `test_smass_*` | 测试库（Django 自动） | 回归时临时创建 |

---

## 6. 验证库的迁移顺序与初始化

命令：`python scripts/db_unify.py <action>`

| 动作 | 内容 | 幂等 |
|---|---|---|
| `plan` | 输出 Django 迁移计划 | 只读 |
| `init` | DROP/CREATE 验证库 + `migrate` | 可重复（重建） |
| `migrate` | 仅执行迁移 | 是 |
| `seed` | 角色组、组织字典、合成账号/学籍/课程、部门 | 是（update_or_create） |
| `verify` | 表数、主键、外键、唯一约束、未应用迁移、账号/学号唯一 | 只读 |
| `rollback` | 删除验证库（仅前缀允许） | 是 |

迁移顺序由 Django 迁移图决定（36 个迁移文件），关键依赖：

```
contenttypes/auth → r21_account → r22_account → smass_organization
→ smass_academic → smass_scheduling/smass_enrollment
→ smass_attendance/activities/clubs/facilities/forum/finance/party/portal
→ smass_workflow/analytics/operations/api → smass_workspace（无模型）
```

验证库实测：127 表、主键齐全、外键 > 0、唯一约束 > 0、无未应用迁移。

---

## 7. 本轮实测结果摘要

| 项 | 结果 |
|---|---|
| 验证库建库+迁移 | PASS（127 表） |
| seed | PASS（3 账号/4 组织/1 学籍/1 教学班） |
| verify | PASS（连接目标/表数/主键/外键/唯一/迁移/角色组/唯一性） |
| 旧数据迁移到验证库 | PASS（6 账号/3 学籍/12 单元/4 关系） |
| 对账 | PASS（账号 3/2/1、学籍 3、组织 12、任职 4、住宿一致、PII 掩码） |
| 断库运行 | PASS（重命名 16 张旧表后三端 13 页全部 200/302） |
| 回滚→再迁移→校验 | PASS |
| 运行时旧库依赖 | 0（`scripts/db_unify_dependency_scan.py`） |
| 正式库指纹 | `940a687d…` 未变 |
