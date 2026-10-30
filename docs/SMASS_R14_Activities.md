# R14 第二课堂、志愿服务与活动管理

> 状态：**TESTED**（28 例：服务 20 + 页面 7 + Chromium E2E 1）
> 代码：`smass_activities/`、`templates/r14/`、`smass/settings_r14.py`、`smass/urls_r14.py`
> 隔离库：`smass_r14_activities`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 活动创建/发布/取消 | 草稿 → 已发布 → 已结束/已取消；只有草稿可发布，过期活动不能发布 | `test_create_and_publish`、`test_publish_twice_rejected`、`test_bad_time_range` |
| 组织者权限 | 只有教师/管理员可创建、发布、关闭、生成认定 | `test_student_cannot_create`、`test_student_cannot_create_activity`（页面） |
| 报名 | 仅已发布 + 未截止 + 未开始；重复报名拒绝 | `test_register_and_capacity_waitlist`、`test_duplicate_registration_rejected`、`test_cannot_register_after_start` |
| 容量与候补 | 满员进候补；已报名者取消后按报名顺序自动递补 | `test_cancel_promotes_waitlist` |
| 取消后重新报名 | 复用同一条记录，状态回到已报名 | `test_cancel_then_register_again` |
| 活动签到 | 签到码 + 时间窗口 + 状态校验 | `test_check_in_success`、`test_wrong_code`、`test_out_of_window`、`test_other_cannot_check_in` |
| 结束补缺勤 | 关闭活动时未签到报名者标缺勤，清空签到码 | `test_close_marks_absent` |
| 学分/时长认定 | 关闭后按签到名单生成待认定，幂等；审批计入累计 | `test_generate_and_approve_credit`、`test_generate_is_idempotent` |
| 职责分离 | 组织者不能认定自己组织的活动学分；驳回必填原因 | `test_organizer_cannot_approve_own_credit`、`test_reject_requires_reason` |
| 页面流程 | 报名/签到/取消、教师发布与关闭、管理员认定 | `test_student_registers_via_page`、`test_student_checks_in_via_page`、`test_credit_approval_via_page`、浏览器 E2E |

## 2. 设计要点

- **报名与候补在一把锁内完成**：`register` / `cancel_registration` 都对 `Activity`
  或报名行 `select_for_update`，容量判断与递补不会出现"两人同时抢最后一个名额"；
- **签到窗口以活动起止时间为准**，签到码默认等于活动结束时间；
- **认定与活动解耦**：活动关闭后才允许生成认定，生成按签到名单、幂等；
- **权限**：与 R13 一致采用角色白名单（teacher/college_admin/system_admin），不改全局矩阵。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_activities --settings=smass.settings_r14
```

实测（2026-10-30）：**28 例 OK**（服务 20 + 页面 7 + Chromium E2E 1）。

## 4. 已知边界

1. 候补递补只按报名时间顺序，不支持"志愿优先/年级优先"等学校自定义规则（需政策输入）；
2. 学分累计按"已认定"汇总，未做学期/年度上限与类别比例校验（学校学分制规则待输入）；
3. 活动签到不区分"迟到"（R13 考勤才有迟到），活动只记签到/缺勤；
4. 活动取消不自动通知已报名学生（通知在 S12 工作流与后续通知服务统一处理）。
