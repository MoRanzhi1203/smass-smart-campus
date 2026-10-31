# 04 教师工作台方案与现状

> 入口 `/teacher/`；辅导员在教师端获得扩展分组。

---

## 1. 页面与能力现状

| 页面 | URL | V2.0 能力 | 状态 |
|---|---|---|---|
| 教学工作台 | `/teacher/` | 今日课程、教学班、待办 | 已有 |
| 我的课程 | `/teacher/courses/` | 授课与人数 | 已有 |
| 教学班 | `/teacher/sections/` | 名单 | 已有；导出待做 |
| 我的课表 | `/teacher/timetable/` | **教学周切换** | IMPLEMENTED |
| 考勤管理 | `/teacher/attendance/` | 发起、结束、统计入口 | 已有 |
| 考勤登记 | `/teacher/attendance/<pk>/` | **整表批量保存**（D02） | IMPLEMENTED |
| 学生事务 | `/teacher/students/` | **教学班 ∪ 负责班级**（A01） | VERIFIED |
| 学生档案 | `/teacher/students/<pk>/` | 对象级校验与 A01 同源 | VERIFIED |
| 审批中心 | `/teacher/approvals/` | 请假/补签/场地审批，**驳回理由必填**（D03） | IMPLEMENTED |
| 负责班级（辅导员） | `/teacher/classes/` | 班级与学生 | 已有 |
| 负责学生（辅导员） | `/teacher/counselor/students/` | 范围校验 | 已有 |
| 请假审批（辅导员） | `/teacher/counselor/leaves/` | 审批 | 已有 |
| 通知与公告 | `/teacher/notices/` | 公告 | 已有 |

---

## 2. 关键修复：兼课辅导员范围（A01，VERIFIED）

- 过去：辅导员分支提前返回，导致“教学班学生在列表可见、详情 403”；
- 现在：`teacher_scope_students = 教学班 ∪ 负责班级`，列表、详情、审批共用；
- 4 例测试：教学班学生可见、列表合并、无关学生 403、撤销任职后失效。

---

## 3. 教师端闭环

1. 发起考勤 → 学生签到/教师批量登记 → 结束 → 学生端同步；
2. 请假审批（含驳回理由）→ 学生端状态与通知；
3. 补签审批 → 覆盖考勤记录为出勤；
4. 场地预约审批；
5. 学生档案查看（对象级 403）。

---

## 4. 明确未完成

| 项 | 说明 |
|---|---|
| 名单导出 | 需接 S25 导出与字段裁剪（F03 导出权限） |
| 班级考勤统计页 | 服务已有 `unit_stats`，缺页面 |
| 辅导员班级活动/组织信息 | 需聚合服务 |
| 审批“已办/历史” | 当前仅待办 |
| 课表调停课 | 依赖 F01 例外表 |

---

## 5. 证据

- 产品层：`TeacherWorkspaceTests`、`CounselorScopeTests`、`CounselorTeachingOverlapTests`、`TeacherBulkAttendanceTests`、`TeacherApprovalReasonTests`；
- 视觉：`.local/evidence/v2/phase/teacher-*.png`。
