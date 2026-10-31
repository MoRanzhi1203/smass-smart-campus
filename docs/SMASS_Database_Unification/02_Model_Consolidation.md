# 02 模型合并与唯一权威源

> 目标：同一业务事实只保留一个权威源；其余字段通过派生、映射或兼容视图处理，
> 避免"两个真相"导致跨端不一致。本轮**不删除模型**（避免破坏 1800 例回归），
> 只明确权威关系并提供一致性校验。

---

## 1. 重复模型/字段清单

| 重复项 | 现状 | 风险 |
|---|---|---|
| 学生姓名/学院/班级 | `Account.display_name`、`StudentProfile.name/college_name/classes_name`、`StudentRecord.name/unit` | 三处可写入，可能不一致 |
| 学号 | `StudentProfile.student_no`、`StudentRecord.student_no` | 双唯一键 |
| 教师姓名/学院 | `Account.display_name`、`TeacherProfile.name/college_name`、`app01.Teacher.name/college_id` | 历史表未退役时三处 |
| 组织 | `OrganizationUnit` vs app01 College/Major/Classes/Grade/Department | 迁移后旧表仍可被误用 |
| 住宿 | `StudentRecord.extra.dormitory` vs app01 Building/Dormitory/Number | 结构弱、无房间外键 |
| 任职 | `OrganizationMembership.role` vs app01 ClassCommittee/LeagueCadres/Classes.counsellor | 角色语义靠字符串 |
| 身份 | `auth.User`（空置） vs `Account` | 误用会导致账号分裂 |
| 通知接收人 | `Notification.recipient`（login_name 字符串） vs `Account` | 改名/删号孤立 |
| 教师职务 | app01 Position/TeacherPosition vs 新模型（无） | 未解决 |

---

## 2. 唯一权威源决策

| 业务事实 | 权威源 | 派生/兼容 | 写入规则 |
|---|---|---|---|
| 登录名、密码、人员类型、启停 | `r21_account.Account` | — | 只经 `r21_account.services` 写入 |
| 姓名 | `StudentRecord.name`（学生）/ `TeacherProfile.name`（教师） | `Account.display_name` 为展示名，允许独立 | 学生改名先改 Record，再同步 Account/Profile |
| 学号 | `StudentRecord.student_no` | `StudentProfile.student_no`（1:1 镜像） | 迁移与建档同时写；新增一致性检查 |
| 学院/专业/班级 | `OrganizationUnit`（Record.unit 指向班级） | `StudentProfile.college_name/classes_name` 为快照 | 组织调整以 Unit 为准 |
| 学籍状态 | `StudentRecord.status` | `StudentProfile` 无状态 | 只经学籍服务 |
| 任课 | `TeachingAssignment` | — | 只经教务服务 |
| 组织成员/任职 | `OrganizationMembership` | app01 任职表（归档） | 迁移与组织服务 |
| 住宿 | `StudentRecord.extra.dormitory` | app01 住宿表（归档） | 当前由迁移/导入写入 |
| 课程/教学班/选课 | `Course/TeachingSection/Enrollment` | — | 教务服务 |
| 审批状态 | 各业务表状态字段（请假/预约/异动） | `WorkflowInstance` 仅用于流程型审批 | 服务层状态机 |
| 通知 | `Notification` | 公告 `Announcement` | 服务层 `notify` |
| 审计 | 各模块审计表 + `AccountAuditLog` | `r22.AccountAuditEvent`（兼容） | 与业务同事务或独立写 |

**规则**：产品页面（`smass_workspace`）只读权威源；`StudentProfile` 仅用于
登录/个人中心展示，且优先读 `StudentRecord`。

---

## 3. 学生身份三表对照

| 字段 | `Account` | `StudentProfile` | `StudentRecord` | 权威 |
|---|---|---|---|---|
| 登录名 | `login_name` | — | — | Account |
| 姓名 | `display_name` | `name` | `name` | Record |
| 学号 | — | `student_no` (unique) | `student_no` (unique) | Record（Profile 镜像） |
| 学院 | `scope_college`（管理范围，非学籍） | `college_name` | `unit.parent.parent` | Unit |
| 班级 | — | `classes_name` | `unit` | Unit |
| 手机 | — | `phone` | `extra.phone`（可选） | Profile（掩码） |
| 身份证 | — | `card_id` | — | 不迁移 |
| 状态 | `is_active`（账号） | — | `status`（学籍） | 各自领域 |
| 入学日期 | — | — | `enrolled_at` | Record |

**一致性要求**：`Account ↔ StudentProfile ↔ StudentRecord` 的学号必须一致；
`Record.unit` 的学院/班级名称应与 Profile 快照一致（组织调整后允许快照滞后，
但迁移/建档时必须一致）。

---

## 4. 兼容视图/派生策略

| 场景 | 策略 |
|---|---|
| 登录后展示姓名 | `Account.display_name`，缺失时回退 `StudentRecord.name` |
| 个人中心学院/班级 | 优先 `StudentRecord.unit` 链，回退 `StudentProfile` 快照 |
| 管理端学籍列表 | 只读 `StudentRecord` + `unit`，不读 Profile |
| 迁移/导入 | 同时写 Record 与 Profile，保证一致性 |
| 旧 app01 读取 | 仅迁移脚本；产品运行时零引用（已扫描确认） |
| 住宿 | 只读 `extra.dormitory`；旧表不再回退（本轮已移除） |

**未采用"数据库视图"**：MySQL 视图会增加迁移复杂度与权限面；
当前用服务层派生即可满足。

---

## 5. 一致性校验

建议并已提供只读检查能力：

| 检查 | 方法 |
|---|---|
| 学号一致 | `StudentRecord.student_no` vs `StudentProfile.student_no` |
| 姓名一致 | `Record.name` vs `Profile.name`（允许 Account 展示名不同） |
| 组织归属 | `Record.unit_id` 非空且 `unit_type='class'` |
| 账号绑定 | 每个 Record 有 Account（或明确未绑定） |
| 教师档案 | 每个 `TeacherProfile` 有 Account 且工号唯一 |
| 角色一致 | 学生有 `student` 角色、教师有 `teacher`、管理员有 `admin` 角色 |

> 可在 `db_unify.py verify` 或后续管理端"数据质量"页扩展；
> 本轮 verify 已覆盖账号唯一、学号唯一、档案 1:1、角色组存在。

---

## 6. 为什么不删除重复模型

| 模型 | 删除影响 | 决策 |
|---|---|---|
| `StudentProfile` | r21 测试 110 例、登录展示、迁移脚本、管理端用户范围（`college_name` 匹配） | 保留，标为兼容派生 |
| `TeacherProfile` | 教师登录展示、迁移、教师范围 | 保留 |
| `app01.*` | 188 例 app01 回归、历史迁移、安全状态表被中间件使用 | 保留 app；旧业务表不进运行时 |
| `auth.User` | Django 权限框架、admin、迁移历史 | 保留空置 |

删除应作为独立任务，配迁移与回归；本轮只做"权威源 + 零运行时依赖"。

---

## 7. 后续 Schema 演进（独立窗口）

1. 住宿独立表（Building/Room/BedAssignment）并从 `extra` 回填；
2. 任职统一表（Appointment）合并班委/团学/社团职务；
3. 教师档案并入 Account 或 `TeacherRecord`，退役 `TeacherProfile`；
4. `Notification.recipient` 改 FK；
5. 课表周次/日期映射；
6. 学号/工号统一为 `PersonIdentifier`（可选）。
