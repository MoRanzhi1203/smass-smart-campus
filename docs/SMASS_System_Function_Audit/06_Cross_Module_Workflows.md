# 06 跨模块业务流程

> 每条流程给出：发起角色、参与角色、入口、步骤、后端调用、数据变化、
> 状态机、权限检查、通知/待办、成功与失败分支、测试证据、闭环缺口。
> 状态机用 `A → B` 表示；"闭环"指产品三端能完成整条链路。

---

## 流程 1：学生入学、建档、分班与学籍维护

| 项 | 内容 |
|---|---|
| 发起角色 | 系统管理员 / 学院管理员（数据准备） |
| 参与角色 | 教务、辅导员、学生 |
| 入口 | `/admin/data-exchange/` → `/r4/import/`；`/r12/placement/`；`/admin/records/` |
| 步骤 | ① 建学院/专业/班级（R4）→ ② 导入学生（S25）→ ③ 自动分班（R12：规则→预览→执行）→ ④ 学生登录查看学籍 |
| 后端 | `organization.services.import_commit`、`enrollment.services.create_placement_preview/apply_placement`、`organization.services.update_student` |
| 数据变化 | `OrganizationUnit`、`StudentRecord`（unit/enrolled_at/extra）、`DataImportJob`、`PlacementBatch/Assignment`、`StudentRecordChange` |
| 状态机 | 导入：preview → committed/failed；分班：draft → applied → rolled_back |
| 权限 | 导入/分班：管理员；学生只能读本人 |
| 通知 | 无自动通知（导入结果在页面；分班不通知学生） |
| 成功 | 学生登录 `/student/record/` 看到班级与学籍 |
| 失败 | 导入行错误整体拒绝；分班容量不足抛错并保留预览 |
| 证据 | S25 85 例、R12 43 例、产品层 40 例 |
| 缺口 | 分班后不通知学生；产品无分班入口（专业工具） |

---

## 流程 2：学年学期、课程、教学班与选课

| 项 | 内容 |
|---|---|
| 发起角色 | 系统管理员 |
| 参与角色 | 教师、学生 |
| 入口 | `/admin/academics/`、`/admin/sections/`、`/r5/enroll/` |
| 步骤 | ① 建学年（是否当前）→ ② 建学期 → ③ 建课程 → ④ 建教学班 → ⑤ 分配教师（R5）→ ⑥ 学生选课（R5） |
| 后端 | `academic.services.create_year/term/course/section`、`TeachingAssignment`、`Enrollment` |
| 数据变化 | `AcademicYear/Term/Course/TeachingSection/TeachingAssignment/Enrollment` |
| 状态机 | 教学班 open/closed；选课 enrolled/dropped |
| 权限 | 建课/班：`require_system_admin`；选课：学生本人 |
| 通知 | 无 |
| 成功 | 学生 `/student/courses/`、教师 `/teacher/courses/` 出现课程 |
| 失败 | 重复编码、学期越界、容量满 → 提示 |
| 证据 | 产品层建课测试、R5 56 例 |
| 缺口 | 选课/退课/分配教师无产品入口（专业工具） |

---

## 流程 3：智能排课、课表发布与跨端查看

| 项 | 内容 |
|---|---|
| 发起角色 | 系统管理员/教务 |
| 参与角色 | 教师、学生 |
| 入口 | `/admin/scheduling/` → `/r11/plan/` → 学生/教师课表 |
| 步骤 | ① 创建 run → ② 课时需求 → ③ 求解 → ④ 复核冲突 → ⑤ 发布 → ⑥ 三端查看 |
| 后端 | `scheduler`（deterministic-constructive-v1）、`plan_solve/publish/conflicts`、`student_timetable/teacher_timetable` |
| 数据变化 | `ScheduleRun(status, placed, conflicts)`、`ScheduleEntry`、`ScheduleConflict` |
| 状态机 | draft → solved → published |
| 权限 | 求解/发布：管理员；查看：本人/范围 |
| 通知 | 无（发布不推送） |
| 成功 | 学生/教师课表出现条目 |
| 失败 | 硬冲突 > 0 禁止发布；不可行给冲突解释 |
| 证据 | R11 40 例 + `verify_run` + 产品 E2E |
| 缺口 | 发布不通知；课表调整/局部重排无产品入口 |

---

## 流程 4：学生请假、审批与结果同步

| 项 | 内容 |
|---|---|
| 发起角色 | 学生 |
| 参与角色 | 教师、辅导员、学院管理员、系统管理员 |
| 入口 | `/student/attendance/` → `/teacher/approvals/` 或 `/teacher/counselor/leaves/` 或 `/admin/approvals/` |
| 步骤 | ① 学生提交（类型/起止/事由）→ ② 审批人看到待批 → ③ 批准/驳回 → ④ 学生端状态更新 |
| 后端 | `attendance.services.submit_leave/approve_leave/reject_leave/cancel_leave` |
| 数据变化 | `LeaveRequest(status, reviewed_by, reviewed_at, reject_reason)` |
| 状态机 | submitted → approved/rejected/cancelled；approved → closed |
| 权限 | 提交/撤销：本人；审批：范围内教师/辅导员/管理员 |
| 通知 | **不自动发**（依赖页面刷新；`notify` 未被审批调用） |
| 成功 | 学生端显示「已批准」；管理端「请假状态」同状态 |
| 失败 | 重叠/无学籍/已离校/越权 → 提示或 403 |
| 证据 | 产品层 `test_teacher_approves_leave_and_student_sees_it` + E2E + consistency 8/8 |
| 缺口 | 审批结果不推送通知；销假无产品入口 |

---

## 流程 5：考勤签到与异常处理

| 项 | 内容 |
|---|---|
| 发起角色 | 教师/辅导员 |
| 参与角色 | 学生 |
| 入口 | `/teacher/attendance/` → 场次详情 → 学生签到（R13） |
| 步骤 | ① 发起场次（生成签到码）→ ② 学生签到 → ③ 教师补登记 → ④ 结束场次 |
| 后端 | `create_session/sign_in/teacher_mark/close_session` |
| 数据变化 | `AttendanceSession(status, code)`、`AttendanceRecord(status, source, checked_at)` |
| 状态机 | session open → closed；record present/late/absent/leave |
| 权限 | 发起/登记：教师；签到：学生本人 |
| 通知 | 无 |
| 成功 | 学生端考勤记录同步；统计更新 |
| 失败 | 码过期/重复签到/场次关闭 → 错误提示 |
| 证据 | R13 28 例 + 产品冒烟 + 产品层（教师登记路径） |
| 缺口 | 学生签到无产品入口（需 `/r13/sessions/<pk>/sign/`） |

---

## 流程 6：场地预约、审批、签到与释放

| 项 | 内容 |
|---|---|
| 发起角色 | 学生/教师 |
| 参与角色 | 管理员/授权教师 |
| 入口 | `/student/bookings/` → `/admin/booking-approvals/` → 签到/释放（R16） |
| 步骤 | ① 提交预约 → ② 需审批则 pending → ③ 审批 → ④ 使用签到 → ⑤ 释放 |
| 后端 | `facilities.services.create_booking/approve_booking/reject_booking/check_in_booking/release_booking` |
| 数据变化 | `RoomBooking(status, approved_by, checked_in_at, released_at)` |
| 状态机 | pending → approved/rejected；approved → checked_in → released/cancelled |
| 权限 | 预约：本人；审批：`can_approve` + 禁自批 |
| 通知 | 无 |
| 成功 | 申请人端状态同步；同一时段不可重复占用 |
| 失败 | 冲突/资格不足/自批/越权 → 错误或 403 |
| 证据 | R16 42 例 + 产品层 + 冒烟 |
| 缺口 | 签到/释放无产品入口；维护期配置无产品入口 |

---

## 流程 7：社团申请、活动发布与学生报名

| 项 | 内容 |
|---|---|
| 发起角色 | 学生（入社/报名）、系统管理员（活动） |
| 参与角色 | 社团负责人、教师 |
| 入口 | `/student/clubs/`、`/admin/activities/`、`/student/activities/` |
| 步骤 | ① 学生申请入社 → ② 负责人审批（R15）→ ③ 管理员建活动并发布 → ④ 学生报名 → ⑤ 取消/候补递补 |
| 后端 | `clubs.services.apply_join/approve_join`、`activities.services.create_activity/publish_activity/register/cancel_registration` |
| 数据变化 | `ClubMembership(status)`、`Activity(status)`、`ActivityRegistration(status)` |
| 状态机 | 成员：pending → active/left；活动：draft → published → closed；报名：registered/waitlisted → cancelled |
| 权限 | 报名：学生本人；发布：系统管理员；审批：负责人 |
| 通知 | 无 |
| 成功 | 学生端「已报名」；管理端报名数增加 |
| 失败 | 已截止/已开始/重复报名 → 提示 |
| 证据 | R14 32 例、R15 28 例、产品 E2E（建活动）+ 产品层 |
| 缺口 | 入社审批无产品入口；报名成功无通知 |

---

## 流程 8：志愿服务、活动记录与统计

| 项 | 内容 |
|---|---|
| 发起角色 | 活动组织方 |
| 参与角色 | 学生 |
| 入口 | `/admin/activities/`（生成学分）、`/student/volunteer/` |
| 步骤 | ① 活动结束 → ② 生成学分/时长 → ③ 管理员认定 → ④ 学生查看汇总 |
| 后端 | `generate_credits/approve_credit/reject_credit`、`student.volunteer_summary` |
| 数据变化 | `ActivityCredit(status, points, hours)` |
| 状态机 | pending → approved/rejected |
| 权限 | 生成/认定：系统管理员；查看：学生本人 |
| 通知 | 无 |
| 成功 | 学生端志愿时长/学分累计 |
| 失败 | 活动未结束/重复生成 → 提示 |
| 证据 | R14 测试 + 产品冒烟 |
| 缺口 | 人工认定无产品入口（`/r14/credits/`） |

---

## 流程 9：费用账单生成、查询与状态管理

| 项 | 内容 |
|---|---|
| 发起角色 | 财务/管理员 |
| 参与角色 | 学生 |
| 入口 | `/r18/bills/create/`（生成）、`/student/fees/`（查看/缴费） |
| 步骤 | ① 建收费项 → ② 生成账单 → ③ 学生查看 → ④ 缴费 → ⑤ 状态刷新 |
| 后端 | `finance.services.create_fee_item/create_bill/pay_bill` |
| 数据变化 | `FeeItem`、`Bill(total, paid, status)`、`BillItem`、`Payment`、`LedgerEntry` |
| 状态机 | unpaid → partial → paid；退费 refunded |
| 权限 | 生成：财务；缴费：学生本人 |
| 通知 | 无 |
| 成功 | 学生端待缴金额减少、状态变更 |
| 失败 | 超额/已缴清/越权 → 提示 |
| 证据 | R18 34 例 + 产品冒烟 |
| 缺口 | 账单生成/退费无产品入口；缴费无支付渠道（台账登记） |

---

## 流程 10：学生与教师账号管理、角色授权

| 项 | 内容 |
|---|---|
| 发起角色 | 系统管理员 |
| 参与角色 | 被授权用户 |
| 入口 | `/admin/users/` |
| 步骤 | ① 创建账号（或迁移）→ ② 分配角色 → ③ 用户登录落地 → ④ 撤销/停用 |
| 后端 | `Account.objects.create_user`、`account_services.grant_role/revoke_role/set_temporary_password` |
| 数据变化 | `Account`、`AccountRole`、Group、`AccountAuditLog` |
| 状态机 | 角色 granted → revoked；账号 active → inactive |
| 权限 | 仅系统管理员 |
| 通知 | 无（口令仅在页面显示一次） |
| 成功 | 落地页随角色变化（实测学生+教师 → 教师端） |
| 失败 | 登录名重复/非超管 → 提示或 403 |
| 证据 | `test_grant_role_changes_landing`、`product_grant_check.py` 8/8 |
| 缺口 | 教师档案未随账号创建（需手工迁移/旧后台） |

---

## 流程 11：数据导入、校验、提交、错误反馈与导出

| 项 | 内容 |
|---|---|
| 发起角色 | 管理员 |
| 参与角色 | 数据所有者 |
| 入口 | `/admin/data-exchange/` → `/r4/import/` |
| 步骤 | ① 下载模板 → ② 上传 → ③ 预检（零写入）→ ④ 提交（重新校验）→ ⑤ 错误反馈 → ⑥ 导出 |
| 后端 | `data_exchange`（schema/parsing/service）、`organization.import_preview/import_commit`、`export` |
| 数据变化 | `DataImportJob(total/success/error)`、`DataImportRowError`、业务表 |
| 状态机 | previewed → committed/failed；幂等重复 skip |
| 权限 | 管理员（`require_kind` + 服务层） |
| 通知 | 无 |
| 成功 | 批次成功行入库；导出可用 |
| 失败 | 行错误整体拒绝；文件类型/大小/炸弹 → 拒绝 |
| 证据 | S25 85 例 |
| 缺口 | 导入向导无产品 UI（专业工具）；导出无产品按钮 |

---

## 流程 12：系统异常、日志审计与恢复

| 项 | 内容 |
|---|---|
| 发起角色 | 运维/系统 |
| 参与角色 | 管理员 |
| 入口 | `/admin/monitoring/`、`/admin/audit/`、`scripts/` |
| 步骤 | ① 指标/告警发现异常 → ② 查审计日志 → ③ 定位账号/操作 → ④ 备份恢复（隔离库演练）→ ⑤ 验证指纹 |
| 后端 | `RequestMetricsMiddleware`、`AccountAuditLog`、`db_fingerprint.py`、S22 备份脚本 |
| 数据变化 | `RequestMetric`、`AlertEvent`、`AccountAuditLog`；恢复为离线操作 |
| 状态机 | 告警 triggered → acknowledged（无自动处置） |
| 权限 | 管理员读；运维执行脚本 |
| 通知 | 无（告警不推送） |
| 成功 | 指标/日志可定位；恢复演练 PASS |
| 失败 | 无自动恢复；需人工 |
| 证据 | R9 测试、S22 演练、产品冒烟 |
| 缺口 | 无告警通知、无自动恢复、探针无调度器 |

---

## 流程闭环度汇总

| 流程 | 产品闭环 | 主要缺口 |
|---|---|---|
| 1 入学建档分班 | 部分 | 分班/导入无产品入口，无通知 |
| 2 教务建课选课 | 部分 | 选课/分配教师无产品入口 |
| 3 排课发布 | 部分 | 求解无产品入口，发布无通知 |
| 4 请假审批 | **闭环** | 无审批通知、无销假入口 |
| 5 考勤签到 | 部分 | 学生签到无产品入口 |
| 6 场地预约 | **闭环**（审批） | 签到/释放无产品入口 |
| 7 社团活动报名 | 部分 | 入社审批无产品入口 |
| 8 志愿认定 | 部分 | 人工认定无产品入口 |
| 9 费用 | 部分 | 账单生成/退费无产品入口 |
| 10 账号授权 | **闭环** | 教师档案未随建 |
| 11 数据导入 | 部分 | 向导/导出无产品入口 |
| 12 运维恢复 | 部分 | 无告警推送/自动恢复 |
