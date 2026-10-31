# 09 测试与回归

> 基线：`5f297ab` 之前的产品层 108 例；本轮（阶段验收）另跑全量与视觉。

---

## 1. 产品层测试（`smass_workspace`）

| 测试类 | 覆盖 |
|---|---|
| AuthFlowTests | 登录落地、无角色、退出 |
| GuardMatrixTests | 三端 403 矩阵 |
| StudentWorkspaceTests | 学生 15 页、请假、预约创建/取消 |
| TeacherWorkspaceTests | 教师页面、审批、学生档案 |
| CounselorScopeTests | 辅导员范围 |
| CounselorTeachingOverlapTests | 兼课辅导员并集（A01） |
| StudentCourseEnrollTests | 选课/退课/容量/越权（C01） |
| StudentAttendanceActionTests | 签到/补签/销假（C02） |
| StudentActivityCheckinTests | 活动详情/签到（C03） |
| StudentClubTests | 社团详情/退社（C04） |
| StudentBookingAndFeeTests | 签到释放/退费申请（C05/C06） |
| NotificationLinkageTests | 通知联动（F02） |
| TeacherBulkAttendanceTests | 批量登记与越权（D02） |
| TeacherApprovalReasonTests | 驳回理由（D03） |
| AdminOrganizationTests | 组织 CRUD（E01） |
| AdminTeacherTests | 教师档案（E02） |
| AdminSchedulingTests | 排课（E03） |
| AdminWorkflowTests | 工作流（E04） |
| AdminClubManagementTests | 入社/任职（E05） |
| AdminCreditTests | 学分认定（E05） |
| AdminFinanceTests | 财务（E06） |
| AdminDataImportTests | 导入（E07） |
| AdminPaginationTests | 分页（E08/F03） |
| TimetableWeekTests | 教学周（F01） |
| NotificationFlowTests | 通知与已读（F02/C07） |
| AdminConsoleTests | 管理端页面与范围 |

**合计 108 例**，全绿（阶段验收前）。

---

## 2. 全量回归（32 套件）

命令：`python scripts/r10_full_regression.py --json`

结果：见 `.local/evidence/v2/regression_v2.log`（本轮实测，见 §6）。

---

## 3. 迁移与回滚

| 迁移 | 验证 |
|---|---|
| `smass_scheduling/0002`（教学周字段） | 应用 → 回滚 0001 → 再应用，三步 OK |

---

## 4. 视觉验收

`scripts/ui_visual_check_v2.py`：**204 检查，0 溢出，0 空页，PASS**。

---

## 5. Git 准入

`scripts/repo_admission_check.py`：索引与暂存区 0 问题，PASS。

---

## 6. 本轮实测结果

（阶段回归完成后由构建者补入：32 套件 / 1802 例 / 失败数 / 耗时 / 证据路径。）

---

## 7. 复现命令

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

& $py manage.py test smass_workspace --settings=smass.settings_product
& $py scripts\r10_full_regression.py --json
& $py scripts\ui_visual_check_v2.py --base http://127.0.0.1:8050
& $py scripts\repo_admission_check.py
```
