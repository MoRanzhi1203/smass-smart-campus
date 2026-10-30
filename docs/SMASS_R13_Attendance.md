# R13 签到考勤、请假销假与补签

> 状态：**TESTED**（41 例：服务 31 + 页面 8 + Chromium E2E 2）
> 代码：`smass_attendance/`、`templates/r13/`、`smass/settings_r13.py`、`smass/urls_r13.py`
> 隔离库：`smass_r13_attendance`（测试库 `test_smass_r13_attendance`）

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 签到 | 教师创建会话生成 6 位签到码（带过期时间），学生凭码签到 | `test_create_session_generates_code`、`test_sign_in_success`、`test_student_signs_via_page` |
| 签到码安全 | 服务端生成、过期拒绝、错误码拒绝、非本班拒绝 | `test_sign_in_expired_code`、`test_sign_in_wrong_code`、`test_sign_in_other_class_rejected` |
| 签到幂等 | 同一会话同一学生只有一条记录，重复提交返回既有记录 | `test_sign_in_is_idempotent` |
| 迟到判定 | 会话创建后超过 `late_after_minutes` 签到记为迟到 | `test_late_detection` |
| 关闭会话补缺勤 | 关闭时未签到学生自动补"缺勤"，已批准请假者标"请假" | `test_close_session_marks_missing_absent`、`test_close_session_marks_approved_leave` |
| 教师手动标记 | 教师可覆盖任一学生状态（含备注） | `test_teacher_mark_overrides`、`test_teacher_mark_other_class_rejected` |
| 请假 | 学生提交（类型/起止/事由），重叠与重复拒绝 | `test_submit_and_approve`、`test_overlapping_submit_rejected`、`test_bad_range_rejected` |
| 请假审批 | 教师/管理员审批，禁止自批，驳回必填原因 | `test_self_approval_denied`、`test_empty_reason_rejected` |
| 销假 | 仅已批准且已过结束日期可销假 | `test_close_leave_requires_finished`、`test_close_finished_leave` |
| 请假重叠防御 | 审批时再次检查与已批准请假是否重叠 | `test_overlap_rejected_on_approve` |
| 补签 | 仅已关闭会话的缺勤/迟到可补签；重复拒绝 | `test_submit_makeup`、`test_makeup_requires_closed_session`、`test_duplicate_makeup_rejected` |
| 补签生效 | 批准后考勤记录改为出勤（source=makeup） | `test_approve_makeup_overrides_record`、`test_makeup_flow_via_page` |
| 统计 | 单会话与班级出勤率 | `test_unit_stats_rate`、`test_session_stats`、`test_create_sign_close_and_stats`（浏览器） |
| 页面权限 | 学生访问统计页 403、不能审批、只能看自己班级会话 | `test_student_forbidden_on_stats`、`test_student_cannot_approve_leave`、`test_student_cannot_view_other_class_session` |

## 2. 设计要点

### 2.1 考勤对象是行政班，不依赖排课

`AttendanceSession(unit=OrganizationUnit(class), session_date, period)`，
签到主体是 `StudentRecord`（R4 学籍档案）。R11 目前只有排课求解结果、没有选课名单，
因此 R13 不去伪造"教学班学生名单"，等 R11 选课落地后再加"按教学班考勤"的适配层。

### 2.2 签到码与幂等

- 6 位数字，服务端 `secrets.choice` 生成，默认 10 分钟过期，关闭会话即清空；
- 唯一约束 `(session, record)` 保证一人一条；重复/并发提交在 savepoint 内捕获
  `IntegrityError`，返回既有记录而不是 500。

### 2.3 关闭会话的自动补记

`close_session` 在行锁内：

1. 取该班全部在读学生；
2. 已有记录的不动；
3. 无记录且当日有"已批准请假"的标 `leave`；
4. 其余标 `absent`。

### 2.4 请假与销假

- 提交：本人或教务；起止日期、事由必填；与进行中/已批准请假重叠时拒绝；
- 审批：教师/管理员，禁止自批；批准时再次检查与其它已批准请假重叠；
- 销假：仅"已批准 + 已过结束日期"，本人或管理员。

### 2.5 权限模型

现有 RBAC 矩阵中教师只有 `view_data`，考勤管理属于本模块业务权限，
因此 `can_manage` 采用**角色白名单**（teacher / college_admin / system_admin），
无角色一律拒绝；不改全局权限矩阵，避免影响既有验收。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_attendance --settings=smass.settings_r13
```

实测（2026-10-30）：**41 例 OK**（服务 31 + 页面 8 + Chromium E2E 2）。

## 4. 已知边界

1. 迟到以"会话创建时间"为基准（教师上课时创建会话）；若学校以课表时间为准，
   需接入 R11 时间槽后再精确判定；
2. 请假与考勤的"自动标假"只在关闭会话时发生；会话进行中签到时若学生处于
   "已批准请假"状态，当前允许签到（以实际到课为准），需政策确认是否禁止；
3. 补签只处理"缺勤/迟到 → 出勤"，不做"出勤 → 请假"的追溯转换；
4. 统计按学生汇总，未按课程/教师维度汇总（依赖教学班选课落地）。
