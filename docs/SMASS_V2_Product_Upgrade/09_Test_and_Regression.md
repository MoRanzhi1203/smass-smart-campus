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

| 项 | 结果 |
|---|---|
| 套件 | 32 |
| 用例总数 | **1868**（原 1802 + V2.0 新增 66） |
| 通过套件 | 31 / 32 |
| 失败 | `tests_e2e` 1 例（全量运行中） |
| 产品层 | 108 例，exit 0 |
| 视觉 | 204 项，0 溢出 |
| Git 准入 | PASS |

**关于 `tests_e2e` 的唯一失败**：

- 该套件走 legacy 配置 `smass.settings`，覆盖旧 app01 页面，**与本轮 V2.0 改动无代码交集**；
- 单独重跑：`python manage.py test tests_e2e --settings=smass.settings` → **16/16 OK**；
- 判定为已知非确定性（历史上该套件曾出现偶发），不作为 V2.0 回归失败；
- 未修改该套件以“消除失败”，保持其独立证据价值。

证据：`.local/evidence/v2/regression_v2.log`、`ui_visual_check_v2.json`、`phase/*.png`。

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
