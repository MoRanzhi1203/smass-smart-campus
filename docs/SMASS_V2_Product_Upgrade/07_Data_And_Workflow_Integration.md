# 07 数据与跨模块联动

> 数据权威：唯一库 `smass_product_dev`（旧库 `smass` 已物理删除）。
> 本文件记录 V2.0 新增的模型维度、事件联动与仍需收口的部分。

---

## 1. 数据模型变更

| 变更 | 说明 | 迁移 |
|---|---|---|
| `ScheduleEntry.week_from/week_to/week_pattern` | 教学周与单双周（F01） | `smass_scheduling/0002`，已回滚再应用验证 |
| 无其他模型变更 | V2.0 其余为服务/视图/模板层 | — |

---

## 2. 业务事件 → 通知（F02，7/7）

| 事件 | 触发点 | 通知对象 | 事件键 |
|---|---|---|---|
| 请假批准/驳回 | `attendance.services` | 学生 | `leave:<pk>:...` |
| 补签通过/驳回 | `attendance.services` | 学生 | `makeup:<pk>:...` |
| 场地批准/驳回 | `facilities.services` | 申请人 | `booking:<pk>:...` |
| 社团入社通过 | `clubs.services` | 申请学生 | `club:<pk>:...` |
| 活动报名/候补 | `activities.services` | 学生 | `activity:<pk>:register:<record>` |
| 排课发布 | `scheduling.services` | 任课教师 | `schedule:<run>:<account>` |
| 公告发布 | `forum.services` | 按受众（≤200） | `announcement:<pk>:<account>` |

幂等：`Notification(recipient, event_key)` 唯一；通知失败不影响主业务。

---

## 3. 跨端联动已验证

| 链路 | 证据 |
|---|---|
| 请假：学生提交 → 教师审批 → 学生端状态 + 通知 | 产品层 + E2E + consistency |
| 考勤：教师发起/批量登记 → 学生端记录 | 产品层 |
| 场地：预约 → 审批 → 签到 → 释放 | 产品层 |
| 活动：发布 → 报名/候补 → 签到 | 产品层 |
| 排课：求解 → 发布 → 学生/教师课表（按周） | 产品层 + R11 回归 |
| 导入：CSV 预检 → 提交 → 学籍/教学班 | 产品层 |

---

## 4. 仍需收口

| 项 | 说明 |
|---|---|
| 通知 recipient 字符串 | 改 `Account` FK 需迁移 + 回填 |
| 学生端选课时间冲突 | `ScheduleEntry` 未绑定 `TeachingSection` |
| 调停课 | 缺例外表 |
| 组织申请/学籍变更申请 | 缺模型 |
| 数据质量页面 | R7 模型已有，管理端未展示 |
