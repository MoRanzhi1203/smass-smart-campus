# 03 模块功能目录 · Part 2

> 覆盖模块 9–16：考勤、审批、寝室、活动、社团、场地、论坛、财务。

---

## 模块 9：考勤、签到与请销假

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 考勤与请假 |
| 业务目标 | 记录课堂出勤、处理请假/补签、向学生与教师双向同步 |
| 面向账号 | 教师/辅导员（发起/登记/审批）、学生（签到/请假）、管理员（查看） |
| 代码位置 | `smass_attendance/models.py`、`services.py`、`views.py`；产品 `teacher.attendance*`、`student.attendance` |
| 原始来源 | R13 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M9-F01 | 发起考勤场次 | 教师/辅导员 | `/teacher/attendance/` · `teacher.attendance_create` | AttendanceSession | 班级归属、日期 | open | 产品冒烟 + R13 | IMPLEMENTED_AND_VERIFIED |
| M9-F02 | 签到码签到 | 学生 | `/r13/sessions/<pk>/sign/` | AttendanceRecord | 码有效/过期/本人 | present/late | R13 28 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M9-F03 | 教师登记 | 教师 | `/teacher/attendance/<pk>/` · `attendance_mark` | AttendanceRecord | 场次归属 | present/late/absent/leave | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M9-F04 | 结束考勤 | 教师 | `attendance_close` | AttendanceSession | 状态 open | closed | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M9-F05 | 提交请假 | 学生 | `/student/attendance/` · `leave_submit` | LeaveRequest | 区间/事由/重叠 | submitted | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M9-F06 | 撤销请假 | 学生 | `leave_cancel` | LeaveRequest | 本人 + submitted | cancelled | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M9-F07 | 审批请假 | 教师/辅导员/管理员 | `/teacher/approvals/`、`/admin/approvals/` | LeaveRequest | 范围/状态 | approved/rejected | `test_teacher_approves_leave_and_student_sees_it` | IMPLEMENTED_AND_VERIFIED |
| M9-F08 | 提交补签 | 学生 | `/r13/makeups/` | MakeupRequest | 场次/理由 | submitted | R13 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M9-F09 | 审批补签 | 教师/辅导员 | `/teacher/approvals/` | MakeupRequest | 范围 | approved/rejected | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M9-F10 | 考勤统计 | 教师/管理员 | `/r13/stats/`、学生页统计 | 聚合 | 范围 | 只读 | R13 测试 | IMPLEMENTED_AND_VERIFIED |
| M9-F11 | 销假 | 学生/管理员 | 服务 `close_leave` | LeaveRequest | approved | closed | R13 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 | 权限 |
|---|---|---|---|---|
| `/student/attendance/` | 4 统计、最近考勤表、请假表、请假表单 | 提交、撤销 | 「暂无考勤记录」「暂无请假」 | 本人 |
| `/teacher/attendance/` | 场次表、发起表单（班级/日期/节次/说明） | 创建 | 「还没有考勤场次」 | 本人教学班班级 |
| `/teacher/attendance/<pk>/` | 场次信息、学生名单、逐人登记 | 登记、结束 | 「该班级暂无学生」 | 场次归属 |
| `/teacher/approvals/` | 待批请假、待批补签 | 批准/驳回 | 空提示 | 范围 |

### D. 后端业务规则

- `submit_leave`：`select_for_update` 锁学籍；拒绝重叠（submitted/approved）；
  拒绝已离校；写审计。
- `teacher_mark`：场次必须 open；同一学生 upsert 一条记录。
- `approve_leave`：校验状态 submitted；写 `reviewed_by/at`；幂等（重复审批报错）。
- 通知：审批结果写 `Notification`（工作流服务）——当前请假审批**不自动发通知**，
  依赖页面刷新（见 06 流程缺口）。

### E. 验证状态

产品路径（发起/登记/结束/请假/撤销/审批）`IMPLEMENTED_AND_VERIFIED`；
签到码、补签提交、销假 `IMPLEMENTED_NOT_VERIFIED`（有服务/深层页，产品未接入）。

---

## 模块 10：审批、工作流与待办

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 工作流 |
| 业务目标 | 可配置的多节点审批；产生待办与事件记录 |
| 面向账号 | 发起人、审批人（教师/辅导员/管理员） |
| 代码位置 | `smass_workflow/`（models/services/ui_views）；产品 `teacher.approvals`、`admin.approvals` |
| 原始来源 | R6 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M10-F01 | 流程定义/版本 | 管理员 | `/admin/workflows/`、`/r6/definitions/` | WorkflowDefinition/Version | 版本发布校验 | draft→published | R6 41 例 | IMPLEMENTED_AND_VERIFIED |
| M10-F02 | 节点/流转配置 | 管理员 | `/r6/definitions/<pk>/` | WorkflowNode/Transition | 节点唯一、合法流转 | 配置 | R6 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M10-F03 | 发起实例 | 管理员/业务 | `/r6/instances/new/` | WorkflowInstance | 已发布版本 | running | R6 测试 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| M10-F04 | 审批流转 | 审批人 | `/r6/instances/<pk>/action/` | WorkflowEvent | 状态机 | running→completed | R6 测试 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| M10-F05 | 流程待办 | 教师/管理员 | `/teacher/approvals/`、`/admin/approvals/` | ApprovalTask | assignee/status | pending→completed | 产品冒烟 + 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M10-F06 | 通知 | 全部 | `/notifications/` | Notification | recipient | 未读→已读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M10-F07 | 流程事件审计 | 管理员 | 数据层 | WorkflowEvent | 只读 | 追加 | R6 测试 | IMPLEMENTED_AND_VERIFIED |
| M10-F08 | 实例监控 | 管理员 | `/admin/workflows/` | WorkflowInstance | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/admin/workflows/` | 定义表（编码/名称/启用/版本数）、实例表（流程/对象/状态/节点/发起人） | 查看；进专业工具 | 「暂无流程定义/实例」 |
| `/teacher/approvals/` | 流程待办列表 | 完成 | 「没有流程待办」 |
| `/admin/approvals/` | 流程待办列表 | 完成 | 同上 |
| `/r6/definitions/`、`/r6/instances/` | 定义/实例/动作 | 全量管理 | Bootstrap 页 |

### D. 后端业务规则

- `transition`：校验 `from_node→action→to_node`；写 `WorkflowEvent`；
  `_sync_task` 生成/关闭 `ApprovalTask`。
- `complete_task`：仅 assignee 或系统管理员；重复完成报 `ConflictError`。
- 幂等：任务完成使用状态条件；实例乐观锁 `version_no`。
- **缺口**：产品端只"完成待办"，不提供发起实例/定义编辑；
  请假审批**不经过** `smass_workflow`，是 `LeaveRequest` 自身状态机。

### E. 验证状态

待办与实例查看 `IMPLEMENTED_AND_VERIFIED`；发起/流转/定义编辑
`IMPLEMENTED_NOT_VERIFIED`（专业工具可达，产品导航没有）。

---

## 模块 11：寝室与住宿管理

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 住宿 |
| 业务目标 | 展示学生住宿信息；数据来源为学籍扩展字段与历史 app01 表 |
| 面向账号 | 学生（本人）、管理员（学籍详情） |
| 代码位置 | `smass_workspace/services/student.py::dormitory_of`；`StudentRecord.extra`；`app01.Student.building/dormitory` |
| 原始来源 | app01（历史）；产品层读取 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M11-F01 | 查看住宿 | 学生 | `/student/dormitory/` | StudentRecord.extra | 本人 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M11-F02 | 学籍详情住宿 | 管理员 | `/admin/records/<no>/` | 同上 | 范围 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M11-F03 | 历史表回退 | 学生 | 同上 | app01.Student | 学号匹配 | 只读 | 代码路径 | IMPLEMENTED_AND_VERIFIED |
| M11-F04 | 住宿登记/调整 | 管理员 | **无入口** | — | — | — | 无视图/服务 | NOT_IMPLEMENTED |
| M11-F05 | 楼栋/寝室台账 | 管理员 | **无入口** | app01.Building/Dormitory | — | — | 旧表存在 | NOT_IMPLEMENTED（产品） |

### C. 页面说明

`/student/dormitory/`：楼栋/寝室/床位/数据来源；无数据时空状态「暂无住宿信息，
可能为走读」；室友来自 `extra.roommates`，无成员列表则空。

### D. 后端业务规则

- `dormitory_of`：先读 `StudentRecord.extra.dormitory`，缺失时按学号查
  `app01.Student`；两者都无 → `None`（页面空状态，不编造）。
- **缺口**：没有住宿管理服务/页面，寝室数据只能由导入或迁移写入。

### E. 验证状态

查看 `IMPLEMENTED_AND_VERIFIED`；管理 `NOT_IMPLEMENTED`。

---

## 模块 12：校园活动与志愿服务

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 活动与志愿 |
| 业务目标 | 发布活动、报名/候补、签到、认定第二课堂学分与志愿时长 |
| 面向账号 | 系统管理员/活动负责人（管理）、学生（报名） |
| 代码位置 | `smass_activities/`；产品 `admin.activities`、`student.activities/volunteer` |
| 原始来源 | R14 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M12-F01 | 创建活动 | 系统管理员 | `/admin/activities/` · `admin.activity_create` | Activity | 时间/类别/容量 | draft | 产品 E2E | IMPLEMENTED_AND_VERIFIED |
| M12-F02 | 发布活动 | 系统管理员 | `admin.activity_action(publish)` | Activity.status | 状态机 | published | E2E | IMPLEMENTED_AND_VERIFIED |
| M12-F03 | 活动报名 | 学生 | `/student/activities/` | ActivityRegistration | 已发布/未截止/未满 | registered/waitlisted | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M12-F04 | 取消报名 | 学生 | `student.activity_cancel` | ActivityRegistration | 本人/状态 | cancelled（候补递补） | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M12-F05 | 活动签到 | 学生 | `/r14/registrations/<pk>/checkin/` | ActivityRegistration | 签到码 | checked_in | R14 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M12-F06 | 结束活动 | 系统管理员 | `admin.activity_action(close)` | Activity.status | 状态机 | closed | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M12-F07 | 生成学分 | 系统管理员 | `admin.activity_action(credits)` | ActivityCredit | 已结束 | pending credits | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M12-F08 | 学分认定 | 管理员 | `/r14/credits/` | ActivityCredit | 状态机 | approved/rejected | R14 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M12-F09 | 志愿时长汇总 | 学生 | `/student/volunteer/` | ActivityCredit | 已认定 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/admin/activities/` | 活动表（报名数/状态）+ 创建表单 | 创建、发布、结束、生成学分 | 「暂无活动」 |
| `/student/activities/` | 4 统计、活动表（报名状态）、我的报名 | 报名、取消 | 「暂无进行中的活动」 |
| `/student/volunteer/` | 3 统计 + 认定记录表 | 查看 | 「暂无志愿记录」 |

### D. 后端业务规则

- `register`：锁活动行；已开始/已截止/重复报名拒绝；容量满 → 候补。
- `cancel_registration`：registered 取消时自动递补候补第一人。
- `generate_credits`：按报名/签到生成，幂等（已有记录跳过）。
- 拒绝：非系统管理员发布/结束 → 403。

### E. 验证状态

产品闭环（建→发→报→取消→结束→生成学分→学生查看）`IMPLEMENTED_AND_VERIFIED`；
签到与人工认定 `IMPLEMENTED_NOT_VERIFIED`。

---

## 模块 13：团委、学生会与社团

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 社团组织 |
| 业务目标 | 社团台账、成员关系、任职；学生组织（部门）归属 |
| 面向账号 | 学生（申请/查看）、社团负责人（深层管理）、管理员（查看） |
| 代码位置 | `smass_clubs/`、`smass_organization.OrganizationUnit(department)` |
| 原始来源 | R15 + R4 部门；app01.Department/LeagueCadres 迁移 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M13-F01 | 社团名录 | 学生/管理员 | `/student/clubs/`、`/admin/clubs/` | Club | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M13-F02 | 申请入社 | 学生 | `student.club_apply` | ClubMembership | 未加入/社团有效 | pending | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M13-F03 | 审批入社 | 负责人/管理员 | `/r15/memberships/<pk>/approve/` | ClubMembership | 负责人 | active | R15 28 例 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M13-F04 | 任命社团职务 | 负责人/管理员 | `/r15/clubs/<pk>/appoint/` | ClubPost | 任期 | 新增 | R15 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M13-F05 | 卸任 | 负责人 | `/r15/posts/<pk>/end/` | ClubPost | 状态 | ended | R15 测试 | IMPLEMENTED_NOT_VERIFIED |
| M13-F06 | 学生组织名录 | 学生/管理员 | `/student/organizations/`、`/admin/clubs/` | OrganizationUnit(department) | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M13-F07 | 我的组织归属 | 学生 | `/student/organizations/` | OrganizationMembership | 本人 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M13-F08 | 创建社团 | 管理员 | `/r15/clubs/create/` | Club | 编码唯一 | 新增 | R15 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/student/clubs/` | 我的社团 chips、社团表（类别/指导/简介/状态） | 申请加入 | 「暂无社团」 |
| `/admin/clubs/` | 社团表、学生组织列表 | 查看 | 空提示 |
| `/student/organizations/` | 组织名录、我的归属、我的班级 | 查看 | 「暂未加入学生组织」 |

### D. 后端业务规则

- `apply_join`：一人一社唯一有效关系；已加入/待审拒绝。
- `is_leader`：`ClubMembership(role=leader,status=active)` 或有效 `ClubPost`。
- 拒绝：非负责人审批 → `PermissionDenied`。

### E. 验证状态

查看与申请 `IMPLEMENTED_AND_VERIFIED`；审批/任职/建社
`IMPLEMENTED_NOT_VERIFIED`（深层页可用，产品未接入）。

---

## 模块 14：场地、教室、实验室与预约

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 场地资源 |
| 业务目标 | 场地台账、可用时段、资格、维护期、预约与审批、签到/释放 |
| 面向账号 | 系统管理员（建档）、师生（预约）、管理员/授权教师（审批） |
| 代码位置 | `smass_facilities/`；产品 `admin.facilities/booking_approvals`、`student.bookings` |
| 原始来源 | R16 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M14-F01 | 场地台账 | 全员 | `/admin/facilities/`、`/student/bookings/` | Room/Building | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M14-F02 | 新建场地 | 系统管理员 | `admin.room_create` | Room | 编码唯一/容量≥0 | 新增（status=open） | `test_admin_creates_room` | IMPLEMENTED_AND_VERIFIED |
| M14-F03 | 预约申请 | 师生 | `/student/bookings/` | RoomBooking | 时间/冲突/资格 | pending/approved | 产品冒烟 + R16 42 例 | IMPLEMENTED_AND_VERIFIED |
| M14-F04 | 取消预约 | 师生 | `student.booking_cancel` | RoomBooking | 本人/状态 | cancelled + released_at | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M14-F05 | 管理员审批 | 管理员/授权教师 | `/admin/booking-approvals/`、`/teacher/approvals/` | RoomBooking | 范围/禁自批 | approved/rejected | 产品冒烟 + R16 | IMPLEMENTED_AND_VERIFIED |
| M14-F06 | 签到/释放 | 预约人 | `/r16/bookings/<pk>/checkin/`、`/release/` | RoomBooking | 本人 | checked_in/released | R16 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M14-F07 | 维护期/可用时段 | 管理员 | `/r16/rooms/<pk>/` | MaintenanceWindow/RoomAvailability | 时间区间 | 配置 | R16 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M14-F08 | 资格授予 | 管理员 | `/r16/`（数据） | RoomQualification | 账号/到期 | 新增 | R16 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M14-F09 | 教室课表 | 管理员 | `/r11/timetable/room/<id>/` | ScheduleEntry | 管理员 | 只读 | R11 测试 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/student/bookings/` | 我的预约表、申请表单（场地/起止/用途/人数） | 申请、取消 | 「暂无预约记录」 |
| `/admin/facilities/` | 场地表（类型/容量/规则/预约数/状态）+ 新增表单 | 新增 | 「暂无场地」 |
| `/admin/booking-approvals/` | 待批预约表 | 批准/驳回 | 「没有待审批预约」 |
| `/teacher/approvals/` | 场地预约审批块 | 批准/驳回 | 空提示 |

### D. 后端业务规则

- `create_booking`：`select_for_update(room)` 串行化；冲突检测；可用时段；
  资格校验；需审批 → pending，否则 approved；**禁止自批**。
- 占用状态：pending/approved/checked_in 均占用；释放写 `released_at`。
- 拒绝：非授权审批 → `FacilityError`；自批 → `SELF_APPROVAL_DENIED`。

### E. 验证状态

台账/预约/审批/取消 `IMPLEMENTED_AND_VERIFIED`；
签到/释放/维护期/资格 `IMPLEMENTED_NOT_VERIFIED`。

---

## 模块 15：校园论坛与通知

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 论坛与公告 |
| 业务目标 | 板块/帖子/评论/举报；公告发布与按受众展示 |
| 面向账号 | 师生（发帖/评论/举报）、管理员（公告/处置） |
| 代码位置 | `smass_forum/`；产品 `admin.notices`、`student/teacher.notices` |
| 原始来源 | R17 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M15-F01 | 公告列表 | 管理员 | `/admin/notices/` | Announcement | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M15-F02 | 创建公告 | 系统管理员 | `admin.announcement_create` | Announcement | 标题/正文/受众 | draft→published | 产品 E2E | IMPLEMENTED_AND_VERIFIED |
| M15-F03 | 学生/教师看公告 | 学生/教师 | `/student/notices/`、`/teacher/notices/` | Announcement | audience | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M15-F04 | 论坛板块/帖子 | 师生 | `/r17/forum/` | Board/Post/Comment | 状态/权限 | 发布/隐藏 | R17 26 例 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| M15-F05 | 举报与处置 | 师生/管理员 | `/r17/reports/` | Report | 状态机 | open→resolved | R17 测试 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| M15-F06 | 公告发布 | 系统管理员 | `admin.announcement_publish` | Announcement | 状态 | published | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/admin/notices/` | 公告表 + 发布表单（标题/正文/受众/立即发布） | 创建、发布 | 「暂无公告」 |
| `/student/notices/`、`/teacher/notices/` | 公告列表（标题/正文/受众/时间） | 查看 | 「暂无公告」 |

### D. 后端业务规则

- `create_announcement` + `publish_announcement`：状态机；受众 all/student/teacher。
- 论坛：内容状态（visible/hidden/removed）；举报处置动作白名单。
- 拒绝：非系统管理员创建/发布公告 → 403。

### E. 验证状态

公告闭环 `IMPLEMENTED_AND_VERIFIED`；论坛与举报
`IMPLEMENTED_NOT_VERIFIED`（R17 深层页可用，产品无入口）。

---

## 模块 16：账单、财务与费用

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 财务 |
| 业务目标 | 收费项、账单、缴费登记、退费审批、台账 |
| 面向账号 | 学生（查/缴本人）、财务授权（深层）、管理员（深层/只读） |
| 代码位置 | `smass_finance/`；产品 `student.fees` |
| 原始来源 | R18 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M16-F01 | 查看本人账单 | 学生 | `/student/fees/` | Bill | 本人 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M16-F02 | 自助缴费 | 学生 | `student.fee_pay` | Bill/Payment/LedgerEntry | 余额/状态 | unpaid→paid | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M16-F03 | 收费项/账单创建 | 财务/管理员 | `/r18/fee-items/create/`、`/r18/bills/create/` | FeeItem/Bill | 金额/对象 | 新增 | R18 34 例 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M16-F04 | 退费申请/审批 | 学生/财务 | `/r18/bills/<pk>/refund/`、`/r18/refunds/` | RefundRequest | 状态机 | submitted→approved→paid | R18 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M16-F05 | 台账 | 财务/管理员 | `/r18/ledger/` | LedgerEntry | 只读 | 只读 | R18 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M16-F06 | 账务汇总 | 管理员 | `/admin/` | 聚合 | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

`/student/fees/`：3 统计（应缴/已缴/待缴）、账单表（账单号/学期/金额/截止/状态/缴纳）；
空状态「暂无账单」；页脚说明"缴费为校内台账登记，不接真实支付"。

### D. 后端业务规则

- `pay_bill`：金额校验（不超过待缴）；幂等键 `Payment.reference`；
  写 `Payment` + `LedgerEntry`；刷新 `Bill.status`。
- 退费：申请→审批→出纳执行三步；金额不超过已缴。
- 拒绝：非本人/非财务 → `PermissionDenied`。

### E. 验证状态

学生查看/缴费 `IMPLEMENTED_AND_VERIFIED`；
收费项/退费/台账 `IMPLEMENTED_NOT_VERIFIED`（深层页可用，产品无入口）。
