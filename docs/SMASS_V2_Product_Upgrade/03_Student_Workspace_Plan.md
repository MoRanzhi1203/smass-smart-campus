# 03 学生工作台方案与现状

> 基线：`docs/SMASS_V2_Product_Upgrade/01_Function_Task_Matrix.md`
> 学生端入口 `/student/`，15 个页面；本文件记录 V2.0 已完成、已验证与仍缺的部分。

---

## 1. 页面与能力现状

| 页面 | URL | V2.0 能力 | 状态 |
|---|---|---|---|
| 学习工作台 | `/student/` | 指标、今日课表、待办、公告 | 已有（V1） |
| 我的课表 | `/student/timetable/` | **教学周切换**（F01），按周过滤单双周 | IMPLEMENTED |
| 我的课程 | `/student/courses/` | **可选课程、选课、退选**（C01） | IMPLEMENTED |
| 学籍信息 | `/student/record/` | 学籍、变更时间线、寝室 | 已有；变更申请待做 |
| 考勤与请假 | `/student/attendance/` | **签到码、补签申请/记录、销假**（C02） | IMPLEMENTED |
| 费用与账单 | `/student/fees/` | 缴费、**账单详情、退费申请**（C06） | IMPLEMENTED |
| 场地预约 | `/student/bookings/` | 预约、取消、**签到、释放**（C05） | IMPLEMENTED |
| 活动与志愿 | `/student/activities/` | 报名、取消、**详情、候补位、签到**（C03） | IMPLEMENTED |
| 志愿服务 | `/student/volunteer/` | 学分/时长汇总 | 已有 |
| 社团 | `/student/clubs/` | **详情、申请进度、退社、任职**（C04） | IMPLEMENTED |
| 学生组织 | `/student/organizations/` | 名录与我的归属 | 已有（只读） |
| 我的寝室 | `/student/dormitory/` | 住宿信息（只读 `extra`） | 已有 |
| 通知公告 | `/student/notices/` | 公告列表 | 已有 |
| 通知中心 | `/notifications/` | **逐条已读、全部已读、未读高亮**（C07） | IMPLEMENTED |
| 个人中心 | `/profile/` | 账号、角色、组织、改密入口 | 已有 |

---

## 2. 已闭环的日常业务

1. **选退课**：容量、重复、学期、状态校验；退选后可重选；写 `EnrollmentHistory`。
2. **签到/补签/销假**：签到码校验、过期与窗口；补签需已关闭场次且本人缺勤；销假要求已批准且假期结束。
3. **场地**：预约 → 审批 → 签到 → 释放；释放后时段可被再次预约。
4. **活动**：报名/候补/取消、详情与签到（活动窗口 + 签到码）。
5. **社团**：申请、进度、退社、任职展示。
6. **费用**：账单明细、台账缴费、退费申请（审批结果可见）。
7. **通知**：逐条/全部已读，未读计数与高亮。

---

## 3. 明确未完成

| 项 | 原因 | 后续 |
|---|---|---|
| 学籍变更申请 | 已完成：手机号/住宿/住址可在线申请（C07），审批后生效；**同字段去重为应用层校验**（MySQL 不支持条件唯一约束，数据库未创建该约束） | `StudentChangeRequest` + 服务 + 页面 |
| 时间冲突检测（C01） | `ScheduleEntry` 未与 `TeachingSection` 建立时段映射 | 与 F01 后续一起补 |
| 组织申请（加入部门） | 无申请模型 | 与 C07 一并设计 |
| 课表按日期（非周模板） | 排课为周模板 | 后续 `ScheduleEntryDate` |

---

## 4. 证据

- 产品层测试：`smass_workspace/tests/test_workspace.py`（108 例，含学生端选课/考勤/活动/社团/场地/费用用例）；
- 视觉：`.local/evidence/v2/phase/student-*.png`（4 视口 × 3 缩放）；
- 页面探针：`/student/courses/`、`/student/attendance/` 200 且区块渲染。
