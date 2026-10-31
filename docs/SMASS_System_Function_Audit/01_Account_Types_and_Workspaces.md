# 01 账号类型与工作台说明

> 依据：`r21_account.models`（`RoleCode`/`PersonType`/`Account`）、
> `r21_account/authorization.py`、`smass_workspace/navigation.py`、
> `smass_workspace/permissions.py`、各模块服务函数的角色判定。
> 所有菜单与页面均可在 `05_Page_and_Route_Catalog.md` 找到对应路由。

---

## 0. 账号类型总览

系统**只有 4 个角色编码**（`RoleCode`）：`system_admin`、`college_admin`、
`teacher`、`student`。其它"身份"不是独立角色，而是**组织关系、权限或业务字段**的组合。

| 账号类型 | 判定依据 | 是否独立角色 | 登录后落地 | 可多角色 |
|---|---|---|---|---|
| 学生 | `RoleCode.STUDENT` | 是 | `/student/` | 是 |
| 普通教师 | `RoleCode.TEACHER` 且无辅导员关系 | 是 | `/teacher/` | 是 |
| 辅导员 | `RoleCode.TEACHER` + `OrganizationMembership(role='counselor')` | 否（教师叠加组织关系） | `/teacher/` | 是 |
| 学院管理员 | `RoleCode.COLLEGE_ADMIN` + `scope_college` | 是 | `/admin/` | 是 |
| 系统管理员 | `RoleCode.SYSTEM_ADMIN` 或 `is_superuser` | 是 | `/admin/` | 是 |
| 班委 | `OrganizationMembership(role='class_committee')` | 否 | 随主角色 | 是 |
| 团学干部 | `OrganizationMembership(role='league_cadre')` | 否 | 随主角色 | 是 |
| 社团负责人 | `ClubMembership(role=leader)` 或 `ClubPost` | 否 | 随主角色 | 是 |
| 活动负责人 | `Activity.organizer` + 服务层 `can_manage` | 否 | 随主角色 | 是 |
| 财务经办 | 授权动作（`can_finance`） | 否 | 随主角色 | 是 |
| 场地管理员 | 授权动作（`can_manage_rooms`） | 否 | 随主角色 | 是 |
| API 客户端 | `smass_api.ApiClient` + Token | 否（非 Account） | 不适用 | — |
| 无角色账号 | 无任何有效 `AccountRole` | — | `/no-role/`（403） | — |

**明确未实现为独立角色**（代码中不存在对应角色/权限/页面）：
班主任、教务管理员、组织管理员、宿管、财务管理员（作为独立角色）——
财务与场地能力以授权动作存在，但没有独立角色编码与独立工作台。

---

## 1. 学生（STUDENT）

### 1.1 身份定义

| 项 | 内容 |
|---|---|
| 名称 | 学生 |
| 数据库模型 | `r21_account.Account`（`person_type='student'`）+ `StudentProfile` + `StudentRecord` |
| 认证方式 | `/login/` → `authenticate(login_name, password)`，密码为 Django 哈希（PBKDF2） |
| 默认工作台 | `/student/`（`workspace:student_home`） |
| 可授予角色 | 可由系统管理员追加 `teacher`/`college_admin`/`system_admin`；默认仅 `student` |
| 所属组织 | `StudentRecord.unit` → 班级 → 专业 → 学院 |
| 多角色 | 支持；`permissions.landing_kind` 按 管理 > 教师 > 学生 取最高 |
| 角色切换 | 顶部"切换工作台"（`available_workspaces`，仅多角色时出现） |
| 启停/密码 | `Account.is_active`；`must_change_password`；`ForcePasswordChangeMiddleware`；管理员重置一次性口令 |

### 1.2 可见菜单与页面（15 页）

| 一级菜单 | 页面 | URL | 视图 | 数据模型 | 可执行操作 | 权限条件 |
|---|---|---|---|---|---|---|
| 我的学习 | 学习工作台 | `/student/` | `student.home` | StudentRecord/Enrollment/ScheduleEntry/AttendanceRecord/Bill/Activity/Announcement | 查看、跳转 | `require_kind('student')` |
| 我的学习 | 我的课表 | `/student/timetable/` | `student.timetable` | Enrollment/ScheduleEntry | 查看 | 同上 |
| 我的学习 | 我的课程 | `/student/courses/` | `student.courses` | Enrollment/TeachingSection/TeachingAssignment | 查看 | 同上 |
| 我的学习 | 学籍信息 | `/student/record/` | `student.record` | StudentRecord/StudentRecordChange | 查看 | 同上 |
| 日常事务 | 考勤与请假 | `/student/attendance/` | `student.attendance` | AttendanceRecord/LeaveRequest | 查看、提交请假、撤销本人待批 | 同上 + 服务层本人校验 |
| 日常事务 | 费用与账单 | `/student/fees/` | `student.fees` | Bill/Payment/LedgerEntry | 查看、缴费（台账） | 同上 |
| 日常事务 | 场地预约 | `/student/bookings/` | `student.bookings` | Room/RoomBooking | 查看、申请、取消 | 同上 + `can_book` |
| 日常事务 | 我的寝室 | `/student/dormitory/` | `student.dormitory` | StudentRecord.extra（+ app01 回退） | 查看 | 同上 |
| 校园生活 | 活动与志愿 | `/student/activities/` | `student.activities` | Activity/ActivityRegistration | 查看、报名、取消 | 同上 |
| 校园生活 | 志愿服务 | `/student/volunteer/` | `student.volunteer` | ActivityCredit | 查看 | 同上 |
| 校园生活 | 社团 | `/student/clubs/` | `student.clubs` | Club/ClubMembership/ClubPost | 查看、申请加入 | 同上 |
| 校园生活 | 学生组织 | `/student/organizations/` | `student.organizations` | OrganizationUnit/OrganizationMembership | 查看 | 同上 |
| 消息 | 通知公告 | `/student/notices/` | `student.notices` | Announcement（audience=student/all） | 查看 | 同上 |
| 消息 | 通知中心 | `/notifications/` | `common.notifications` | Notification/Announcement | 查看（打开即已读） | 登录用户 |
| 账号 | 个人中心 | `/profile/` | `common.profile` | Account/StudentRecord/OrganizationMembership | 查看 | 登录用户 |

### 1.3 业务操作权限

| 操作 | 学生 | 证据 |
|---|---|---|
| 查看本人数据 | ✅ | `student_record(account)`、`Enrollment.objects.filter(account=...)` |
| 查看他人数据 | ❌ | 无对应端点；`can_access_student` 对学生仅返回本人 |
| 新增 | ⚠️ 仅限业务申请（请假/预约/报名/入社） | 各 `submit_*`/`create_booking`/`register`/`apply_join` |
| 编辑 | ❌ | 无学生端编辑端点 |
| 删除 | ❌ | 无删除端点；撤销是状态变更 |
| 提交 | ✅ 请假、预约、活动报名、入社 | 同上 |
| 撤销 | ✅ 本人待批请假、本人预约、本人报名 | `cancel_leave`/`cancel_booking`/`cancel_registration` |
| 审批/驳回 | ❌ | 审批端点由教师/管理端守卫 |
| 导入/导出 | ❌ | 导入导出端点 `admin_only` |
| 发布/归档 | ❌ | 公告/活动发布为 `require_system_admin` |
| 系统配置 | ❌ | `require_system_admin` |

### 1.4 数据访问范围

- **只能查看本人**：学籍、考勤、请假、账单、预约、报名、社团成员关系。
- 课表/课程来自本人 `Enrollment`；寝室来自本人 `StudentRecord.extra`。
- 敏感字段：`StudentProfile.phone/card_id` 在学生端只展示本人；
  `authorization.redact` 对管理员也有掩码策略（仅系统管理员可取原值）。
- 角色叠加风险：学生若被追加 `teacher`，将获得教师工作台与「本人教学班学生」范围；
  若被追加 `college_admin`，将获得本院管理端。**这是角色叠加的正常结果，
  但审计确认：`landing_kind` 只影响落地，不限制访问其它已授权端。**
  未发现"学生角色"会扩大教师/管理范围的反向放大。

### 1.5 实际操作流程（请假）

1. 学生 `/login/` 登录 → 落地 `/student/`；
2. 进入「考勤与请假」→ 填写类型/起止/事由 → 提交；
3. 后端 `submit_leave`：校验学籍存在、本人、日期区间、事由、无重叠进行中请假；
   写 `LeaveRequest(status=submitted)` 并记审计；
4. 教师/辅导员端「审批中心」出现该申请；审批后 `status=approved/rejected`；
5. 学生刷新页面看到「已批准/已驳回」；管理端「请假状态」表显示同一状态。

**数据库影响**：`smass_attendance_leaverequest` 新增/更新一行；审计日志一条。
**失败分支**：无学籍 / 重叠 / 已离校 / 日期非法 → 页面 `messages.error`，不写库。

---

## 2. 普通教师（TEACHER）

### 2.1 身份定义

| 项 | 内容 |
|---|---|
| 名称 | 普通教师（未授予辅导员关系） |
| 数据库模型 | `Account(person_type='teacher')` + `TeacherProfile` + `TeachingAssignment` |
| 认证 | 同统一登录 |
| 默认工作台 | `/teacher/` |
| 可授予角色 | 默认 `teacher`；可叠加其它角色 |
| 所属组织 | `TeacherProfile.college_name`；任课关系 `TeachingAssignment` |
| 多角色 | 支持 |
| 角色切换 | 顶部切换（多端时） |
| 启停/密码 | 同学生；教师账号 `is_staff=True`（仅 Django 后台，不影响产品守卫） |

### 2.2 可见菜单与页面（10 页，无辅导员分组）

| 一级菜单 | 页面 | URL | 视图 | 数据模型 | 操作 | 权限 |
|---|---|---|---|---|---|---|
| 教学工作 | 教学工作台 | `/teacher/` | `teacher.home` | TeachingAssignment/Enrollment/ScheduleEntry/LeaveRequest | 查看、快捷入口 | `require_kind('teacher')` |
| 教学工作 | 我的课程 | `/teacher/courses/` | `teacher.courses` | TeachingSection/Course/Enrollment | 查看 | 本人教学班 |
| 教学工作 | 教学班 | `/teacher/sections/` | `teacher.sections` | TeachingSection/Enrollment | 查看名单 | 本人教学班 |
| 教学工作 | 我的课表 | `/teacher/timetable/` | `teacher.timetable` | ScheduleEntry（teacher=本人） | 查看 | 本人 |
| 学生事务 | 考勤管理 | `/teacher/attendance/` | `teacher.attendance` | AttendanceSession | 查看、发起 | 本人教学班班级 |
| 学生事务 | 考勤登记 | `/teacher/attendance/<pk>/` | `teacher.attendance_detail` | AttendanceSession/AttendanceRecord/StudentRecord | 逐人登记、结束 | 场次归属校验 |
| 学生事务 | 学生事务 | `/teacher/students/` | `teacher.students` | Enrollment/StudentRecord | 查看 | 教学班范围 |
| 学生事务 | 学生档案 | `/teacher/students/<pk>/` | `teacher.student_detail` | StudentRecord/AttendanceRecord/LeaveRequest/Enrollment | 查看 | 对象级校验 |
| 学生事务 | 审批中心 | `/teacher/approvals/` | `teacher.approvals` | LeaveRequest/MakeupRequest/ApprovalTask/RoomBooking | 批准/驳回/完成 | 范围内 |
| 消息 | 通知与公告 | `/teacher/notices/` | `teacher.notices` | Announcement（teacher/all） | 查看 | 教师 |

### 2.3 业务操作权限

| 操作 | 权限 | 证据 |
|---|---|---|
| 查看本人教学班/学生 | ✅ | `my_sections`/`section_students` |
| 查看非本人教学班学生 | ❌ 403 | `can_access_student` → `scoped_student_records` |
| 发起考勤 | ✅ | `create_session` + 视图归属校验 |
| 登记/结束考勤 | ✅ | `teacher_mark`/`close_session` |
| 审批请假/补签 | ✅（范围内） | `approve_leave`/`reject_leave`/`approve_makeup` |
| 审批场地预约 | ✅ 仅当 `can_approve` | `pending_bookings` + `can_approve` |
| 完成流程待办 | ✅ 仅本人 assignee | `task.assignee == login_name` |
| 建课/建班/导入/授权 | ❌ 403 | `require_system_admin` |
| 查看管理端 | ❌ 403 | `require_kind('admin')` |

### 2.4 数据访问范围

- 授课学生：`Enrollment(section in TeachingAssignment)`；
- 考勤班级：上述学生所在 `OrganizationUnit`；
- 请假/补签：上述学生的记录；
- 场地审批：`can_approve(account)`（授权动作）；
- 敏感字段：学生手机/身份证默认掩码（`authorization.redact`）。

### 2.5 流程（审批请假）

1. 教师登录 → `/teacher/approvals/`；
2. 列表显示范围内 `LeaveRequest(status=submitted)`；
3. 点击「批准」→ `approve_leave` → `status=approved`、`reviewed_by/at` 写入；
4. 学生端刷新显示「已批准」；
5. 管理端「请假状态」表同样显示「已批准」。

---

## 3. 辅导员（TEACHER + counselor 组织关系）

### 3.1 身份定义

| 项 | 内容 |
|---|---|
| 名称 | 辅导员（教师扩展） |
| 模型 | `Account(teacher)` + `OrganizationMembership(unit=班级, role='counselor', ended_at IS NULL)` |
| 认证/落地 | 同教师，`/teacher/` |
| 判定 | `permissions.is_counselor`：教师角色且存在有效 counselor 关系 |
| 菜单 | 教师菜单 + 「辅导员工作」分组（负责班级/负责学生/请假审批） |
| 范围 | `counselor_units` → 班级及其子单元学生 |
| 多角色 | 支持；可同时是任课教师 |

### 3.2 扩展页面（3 页）

| 页面 | URL | 视图 | 操作 | 权限 |
|---|---|---|---|---|
| 负责班级 | `/teacher/classes/` | `teacher.classes` | 查看班级与学生 | `is_counselor`，否则 403 |
| 负责学生 | `/teacher/counselor/students/` | `teacher.counselor_students` | 查看 | 同上 |
| 请假审批 | `/teacher/counselor/leaves/` | `teacher.leave_review` | 批准/驳回 | 同上 |

### 3.3 操作权限与范围

| 操作 | 权限 | 证据 |
|---|---|---|
| 查看负责班级/学生 | ✅ | `counselor_units`/`counselor_students` |
| 审批负责学生请假 | ✅ | `leave_action` + 服务层范围 |
| 查看非负责学生 | ❌ 403 | `can_access_student` |
| 教学班学生 | ✅（若同时任课） | 角色叠加：教师范围 ∪ 辅导员范围 |
| 管理端 | ❌ 403 | 无 admin 角色 |

> 叠加检查：辅导员若同时任课，`scoped_student_records` 在 `is_counselor` 分支
> **只返回负责班级学生**，不再叠加教学班学生。这是审计发现的**范围收窄**：
> 兼课辅导员的"教学班学生"在对象级校验中可能被判 403。
> 证据：`permissions.scoped_student_records` 的分支顺序（counselor 先于 teacher）。
> 详见 `08_Gaps_and_Technical_Debt.md` 的 P1 项。

### 3.4 流程（辅导员审批请假）

1. 学生提交请假 → 状态 submitted；
2. 辅导员登录 → `/teacher/` 出现「辅导员工作」；
3. `/teacher/counselor/leaves/` 待批列表 → 批准；
4. `LeaveRequest.status=approved`，学生端同步；
5. 管理端可按范围看到该记录。

---

## 4. 学院管理员（COLLEGE_ADMIN）

### 4.1 身份定义

| 项 | 内容 |
|---|---|
| 名称 | 学院管理员 |
| 模型 | `Account(person_type='admin')` + `AccountRole(college_admin)` + `scope_college` |
| 认证/落地 | `/login/` → `/admin/` |
| 可授予角色 | 默认 college_admin；不可自行授予（需系统管理员） |
| 所属组织 | `scope_college` 字符串匹配 `OrganizationUnit.code` 或 `name` |
| 多角色 | 支持 |
| 启停/密码 | 同统一账号 |

### 4.2 可见菜单与页面（22 页中的 19 页；无系统配置）

管理端导航全部可见，但：
- `/admin/settings/`（系统配置）→ **403**（`require_system_admin`）；
- 用户账号/角色/组织：**只读**（写操作 403）；
- 学年/学期/课程/教学班/场地/活动/公告：**只读**（写操作 403）；
- 学籍档案：可看，编辑表单不渲染（模板 `is_super` 判断），写接口 403；
- 学籍异动/请假/场地审批：可操作（限本院学生）。

### 4.3 业务操作权限

| 操作 | 学院管理员 | 证据 |
|---|---|---|
| 查看本院学籍/用户/组织 | ✅ | `scope_users`/`scope_records` |
| 查看外院数据 | ❌ 403/空集 | `can_access_student`、`college_unit_ids` |
| 创建账号/授角色/停用/重置 | ❌ 403 | `require_system_admin` |
| 建课/建班/建场地/发活动/发公告 | ❌ 403 | 同上 |
| 学籍异动审批 | ✅ 限本院 | `transfer_action`/`status_change_action` + 对象校验 |
| 请假/场地审批 | ✅ 限本院 | `leave_action`/`booking_action` |
| 监控/审计/数据交换 | ✅ 只读 | `require_kind('admin')` |
| 系统配置/权限矩阵/字段策略 | ❌ 403 | `require_system_admin` |

### 4.4 数据范围

- `scope_college` 为空 → 空集（不是全校）；
- 学院子树：`college_unit_ids` 递归收集子单元；
- 学籍：`StudentRecord.unit_id in 子树`；
- 用户：`student_profile.college_name`/`teacher_profile.college_name`/`scope_college` 匹配；
- 角色叠加：若同时是系统管理员，则按系统管理员（全局）。

### 4.5 流程（审批转专业）

1. 学生/管理员提交转专业 → `MajorTransferRequest(status=submitted)`；
2. 学院管理员 `/admin/record-changes/` 看到本院申请；
3. 批准 → `approve_transfer`（校验目标专业/班级）→ approved；
4. 学生端学籍档案与选课按服务层规则更新（`apply_transfer` 需另行执行，见 06 流程缺口）；
5. 外院申请在列表不可见，直接访问 URL → 403。

---

## 5. 系统管理员（SYSTEM_ADMIN / superuser）

### 5.1 身份定义

| 项 | 内容 |
|---|---|
| 名称 | 系统管理员（超级管理员） |
| 模型 | `Account` + `AccountRole(system_admin)`，或 `is_superuser=True` |
| 认证/落地 | `/login/` → `/admin/` |
| 可授予角色 | 全部 4 个角色；可停用/重置任意账号 |
| 组织范围 | 全局（忽略 `scope_college`） |
| 多角色 | 支持；管理权限**不等于**学生/教师数据权限 |

### 5.2 可见菜单与页面（22 页全部）

含 `/admin/settings/`（权限矩阵、字段策略、密码策略）。
学生端/教师端仅当账号同时持有对应角色时可进；否则 403。

### 5.3 业务操作权限

| 操作 | 系统管理员 | 证据 |
|---|---|---|
| 创建账号/授角色/停用/重置 | ✅ | `admin.user_create/user_role/user_toggle/user_reset` |
| 建学年/学期/课程/教学班/场地 | ✅ | `admin.year_create/term_create/course_create/section_create/room_create` |
| 编辑学籍（姓名/状态/班级） | ✅ | `admin.record_update` → `update_student`（乐观锁 + 变更历史） |
| 创建/发布/结束活动、发布公告 | ✅ | `activity_create`/`activity_action`/`announcement_create` |
| 学籍异动/请假/场地审批 | ✅ 全局 | 审批视图 |
| 监控/审计/数据交换 | ✅ | `admin.monitoring/audit/data_exchange` |
| 系统配置 | ✅ | `require_system_admin` |
| 学生/教师端数据 | ❌ 无对应角色时 403 | `require_kind` |

### 5.4 数据范围与特权

- 全局学籍/用户/审批；
- `authorization` 中系统管理员可取敏感字段原值（字段策略允许时）；
- **没有**"绕过业务状态机"的入口：审批仍走服务层状态校验。

### 5.5 流程（授权用户）

1. `/admin/users/` 找到账号 → 选择角色 → 「授予」；
2. `grant_role` 写 `AccountRole` + 同步 Django Group；
3. 该用户重新登录 → `landing_kind` 变化（如学生+教师 → `/teacher/`）；
4. 审计 `AccountAuditLog` 记录；撤销后恢复。

---

## 6. 复合身份（非独立角色）

### 6.1 班委（class_committee）

| 项 | 内容 |
|---|---|
| 判定 | `OrganizationMembership(role='class_committee', unit=班级)` |
| 来源 | app01 `ClassCommittee` 迁移写入；产品无授予界面 |
| 能力 | **当前无专属页面/权限**；仅作为组织关系展示（个人中心/组织页） |
| 证据 | `legacy_migration.py` 写入；`navigation`/`permissions` 未引用该 role |
| 状态 | `PARTIALLY_IMPLEMENTED`（数据存在，业务能力未实现） |

### 6.2 团学干部（league_cadre）

| 项 | 内容 |
|---|---|
| 判定 | `OrganizationMembership(role='league_cadre', unit=部门)` |
| 来源 | app01 `LeagueCadres` 迁移；产品无授予界面 |
| 能力 | 同班委：仅展示，无专属权限 |
| 状态 | `PARTIALLY_IMPLEMENTED` |

### 6.3 社团负责人

| 项 | 内容 |
|---|---|
| 判定 | `ClubMembership(role=leader)` 或有效 `ClubPost`；服务层 `is_leader` |
| 能力 | 审批入社、任命职务（`/r15/` 深层页；产品端未提供社团管理页） |
| 产品入口 | 学生端仅"申请加入"；管理端社团页只读 |
| 状态 | `IMPLEMENTED_NOT_VERIFIED`（服务/深层页有实现，产品路径未接入写操作） |

### 6.4 活动负责人

| 项 | 内容 |
|---|---|
| 判定 | `Activity.organizer` + `activities.services.can_manage` |
| 能力 | 发布/结束/生成学分（深层 `/r14/` 与管理端超管） |
| 产品入口 | 管理端活动管理（超管写）、学生端报名 |
| 状态 | `IMPLEMENTED_AND_VERIFIED`（管理端 E2E 创建/发布/结束；负责人个人入口未产品化） |

### 6.5 财务经办 / 场地管理员

| 项 | 内容 |
|---|---|
| 判定 | 授权动作 `can_finance` / `can_manage_rooms`（`authorization`） |
| 能力 | 深层 `/r18/`、`/r16/` 的账单/场地管理 |
| 产品入口 | 无专属页面；管理端只读 |
| 状态 | `PARTIALLY_IMPLEMENTED`（能力存在，产品未暴露） |

### 6.6 API 客户端

| 项 | 内容 |
|---|---|
| 判定 | `smass_api.ApiClient` + Token（`smass_api_security`） |
| 能力 | `/api/` 接口（`smass_api` 6 条路由），scope/幂等/限流/防重放 |
| 产品入口 | 无专属界面；`smass_api` 已在 `settings_product.INSTALLED_APPS` 注册，`/api/` 路由随 `urls_r10` 挂载 |
| 状态 | `IMPLEMENTED_NOT_VERIFIED`（独立配置有 28 例安全测试；产品路径未做浏览器/接口联调） |

### 6.7 无角色账号

| 项 | 内容 |
|---|---|
| 判定 | `allowed_kinds(account)` 为空 |
| 落地 | `/no-role/`（403） |
| 可访问 | 仅 `/profile/`、`/notifications/`（登录用户共用），其余 403 |
| 状态 | `IMPLEMENTED_AND_VERIFIED`（产品层测试 `test_login_lands_no_role`） |

---

## 7. 多角色组合与权限叠加

| 组合 | 落地 | 可访问端 | 范围变化 | 风险 |
|---|---|---|---|---|
| student + teacher | `/teacher/` | 学生端 + 教师端 | 教师范围（教学班学生） | 无越权；落地由优先级决定 |
| teacher + counselor | `/teacher/` | 教师端 + 辅导员分组 | **仅辅导员班级**（见 §3.3） | 兼课教师的教学班学生可能 403（P1） |
| student + college_admin | `/admin/` | 学生端 + 管理端 | 管理端本院；学生端本人 | 无越权 |
| college_admin + system_admin | `/admin/` | 管理端 | 全局（system 优先） | 符合预期 |
| 任意 + 无 admin 角色 | — | 无管理端 | — | — |

**审计结论**：角色叠加不会把"学生数据范围"扩大为全局；
唯一异常是辅导员分支覆盖教师分支导致的**范围收窄**（不是放大）。

---

## 8. 账号生命周期

| 阶段 | 实现 | 证据 |
|---|---|---|
| 创建 | 管理端「创建账号」或 `Account.objects.create_user` | `admin.user_create` |
| 初始口令 | 随机生成、仅显示一次、`must_change_password=True` | 同上 + `SensitiveResponseMiddleware` |
| 首次登录 | `ForcePasswordChangeMiddleware` 拦截到改密页 | `r21_account/middleware.py` |
| 重置 | 管理端「重置口令」→ `set_temporary_password`（TTL 可配） | `r21_account.services` |
| 停用 | `is_active=False`；登录拒绝 | `admin.user_toggle`、`login_lock_status` |
| 会话失效 | 改密/停用后 `session_epoch` 递增（`AccountSecurityState`） | `app01/middleware/password_lifecycle.py` |
| 审计 | `AccountAuditLog`、`LoginAttempt` | 管理端「安全审计」 |
| 迁移账号 | `LegacyAccountLink` 锚点；密码哈希继承；PII 默认掩码 | `scripts/legacy_migration.py` |
