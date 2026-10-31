# 03 模块功能目录（索引）

> 完整功能清单按业务领域拆为三个分册，避免单文件过长：
>
> - [Part 1：工作台、身份、组织、学籍、教学、选课、排课](03_Module_Catalog_Part1.md)
> - [Part 2：考勤、审批、寝室、活动、社团、场地、论坛、财务](03_Module_Catalog_Part2.md)
> - [Part 3：专项组织、数据交换、分析、通知、运维、安全、app01 未覆盖](03_Module_Catalog_Part3.md)
>
> 每个模块统一结构：A 概述 / B 功能清单 / C 页面说明 / D 后端规则 / E 验证状态。
> 功能状态取值：`IMPLEMENTED_AND_VERIFIED`、`IMPLEMENTED_NOT_VERIFIED`、
> `PARTIALLY_IMPLEMENTED`、`PLACEHOLDER`、`BROKEN`、`NOT_IMPLEMENTED`、`NOT_APPLICABLE`。

## 模块总览（23 个业务域）

| # | 模块 | 主要代码 | 产品入口 | 状态 |
|---|---|---|---|---|
| 1 | 工作台与个人中心 | `smass_workspace` | `/student/`、`/teacher/`、`/admin/`、`/profile/`、`/notifications/` | IMPLEMENTED_AND_VERIFIED |
| 2 | 统一账号、身份与角色权限 | `r21_account`、`smass_workspace/permissions.py` | `/login/`、`/admin/users/`、`/admin/roles/` | IMPLEMENTED_AND_VERIFIED |
| 3 | 组织、学院、专业、年级、班级 | `smass_organization` | `/admin/organizations/`、`/r4/units/` | IMPLEMENTED_AND_VERIFIED（产品只读） |
| 4 | 学生档案与学籍 | `smass_organization`、`smass_enrollment` | `/admin/records/`、`/student/record/` | IMPLEMENTED_AND_VERIFIED |
| 5 | 教师档案与教学管理 | `r21_account.TeacherProfile`、`smass_academic.TeachingAssignment`、`app01.Teacher` | `/teacher/` | PARTIALLY_IMPLEMENTED |
| 6 | 学年、学期、课程、教学班 | `smass_academic` | `/admin/academics/`、`/admin/sections/` | IMPLEMENTED_AND_VERIFIED |
| 7 | 选课与学生名单 | `smass_academic.Enrollment` | `/admin/sections/<pk>/roster/`、`/teacher/sections/` | PARTIALLY_IMPLEMENTED |
| 8 | 排课与三张课表 | `smass_scheduling` | `/admin/scheduling/`、`/student/timetable/`、`/teacher/timetable/` | IMPLEMENTED_AND_VERIFIED（求解走专业工具） |
| 9 | 考勤、签到、请销假 | `smass_attendance` | `/teacher/attendance/`、`/student/attendance/` | IMPLEMENTED_AND_VERIFIED |
| 10 | 审批、工作流、待办 | `smass_workflow` | `/teacher/approvals/`、`/admin/approvals/`、`/admin/workflows/` | PARTIALLY_IMPLEMENTED |
| 11 | 寝室与住宿 | `StudentRecord.extra`、`app01.Student` | `/student/dormitory/`、`/admin/records/<no>/` | PARTIALLY_IMPLEMENTED |
| 12 | 校园活动与志愿服务 | `smass_activities` | `/admin/activities/`、`/student/activities/` | IMPLEMENTED_AND_VERIFIED |
| 13 | 团委、学生会、社团 | `smass_clubs`、`smass_organization`（部门） | `/admin/clubs/`、`/student/clubs/` | PARTIALLY_IMPLEMENTED |
| 14 | 场地、教室、实验室与预约 | `smass_facilities` | `/admin/facilities/`、`/admin/booking-approvals/`、`/student/bookings/` | IMPLEMENTED_AND_VERIFIED |
| 15 | 校园论坛与通知 | `smass_forum` | `/admin/notices/`、`/student/notices/`、`/r17/` | PARTIALLY_IMPLEMENTED |
| 16 | 账单、财务与费用 | `smass_finance` | `/student/fees/`、`/r18/` | PARTIALLY_IMPLEMENTED |
| 17 | 组织专项业务（党建/专项） | `smass_party` | `/r19/` | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| 18 | 数据导入、导出与模板 | `smass_data_exchange`、`smass_organization` | `/admin/data-exchange/`、`/r4/import/` | IMPLEMENTED_AND_VERIFIED（导入走专业工具） |
| 19 | 统计分析与报表 | `smass_analytics`、`smass_operations` | `/admin/`、`/r7/` | PARTIALLY_IMPLEMENTED |
| 20 | 消息通知 | `smass_workflow.Notification`、`smass_forum.Announcement` | `/notifications/`、三端通知页 | IMPLEMENTED_AND_VERIFIED |
| 21 | 系统配置、运维、监控 | `smass_operations`、`r21_account` | `/admin/monitoring/`、`/admin/settings/` | IMPLEMENTED_AND_VERIFIED |
| 22 | 安全审计、备份、权限、灾难恢复 | `r21_account`、`smass_audit`（独立）、脚本 | `/admin/audit/` | PARTIALLY_IMPLEMENTED |
| 23 | app01 尚未被产品覆盖的功能 | `app01` | 旧入口（未挂载产品） | PARTIALLY_IMPLEMENTED |

## 功能计数

| 分册 | 模块数 | 功能条目 |
|---|---|---|
| Part 1（M1–M8） | 8 | 65 |
| Part 2（M9–M16） | 8 | 62 |
| Part 3（M17–M23） | 7 | 53 |
| 合计 | 23 | **180** |

> 计数规则：每个模块的"B 功能清单"中一行算 1 个功能条目（含子功能拆分）；
> 与 `09_Test_and_Evidence_Index.md` 的证据表一一对应。
