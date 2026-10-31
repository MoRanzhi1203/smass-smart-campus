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

### 6.1 阶段验收（第 16 轮，基线较早）

| 项 | 结果 |
|---|---|
| 套件 | 32 |
| 用例总数 | 1868 |
| 通过套件 | 31 / 32 |
| 失败 | `tests_e2e` 1 例（偶发，单独重跑 16/16 OK） |

### 6.2 最终验收（V2.0 收尾）

| 项 | 结果 |
|---|---|
| 套件 | **32** |
| 用例总数 | **1896** → 交付前重跑 **1902**（新增档案同步等 6 例） |
| 失败 | **0**（两次均 exit 0） |
| 产品层 | **142 例** |
| 明色视觉 | **204 项 / 0 溢出 / 0 空页 / PASS** |
| 暗色视觉 | **68 项 / 0 溢出 / PASS** |
| 无障碍（明/暗） | 各 **11 页 / 0 问题 / PASS** |
| Git 准入 | PASS |

证据：`.local/evidence/v2/regression_final.log`（1896）、`regression_delivery.log`（1902）、`.local/evidence/v2/final/*.json`。

---

## 7. 性能基准（F05）

脚本：`scripts/perf_baseline_v2.py`（临时测试库：创建 → 测量 → 销毁，不触碰产品库）。

数据规模：1000 账号 / 500 学籍 / 50 教学班 / 500 选课；导入 500 行 CSV。

| 路径 | 优化前 | 优化后 |
|---|---|---|
| 管理端用户列表（第 1 页） | 199.0 ms / **202 queries** | **53.6 ms / 3 queries** |
| 管理端学籍列表 | 47–101 ms / 2 queries | 2 queries |
| 管理总览聚合 | 22–56 ms / 22 queries | 22 queries |
| 学生课表查询 | 6.5–14 ms / 3 queries | 3 queries |
| 教师学生范围 | 3.5–5.6 ms / 2 queries | 2 queries |
| 导入 500 行 | preview 2.4 s / commit 11.0 s / 峰值 4.2 MB | 同 |

**发现与修复**：`services/admin.py::users` 对每个账号调用 `active_roles()`，产生 N+1（202 次查询）；
改为一次批量查询 `AccountRole` 后按账号分组，查询降到 3 次，耗时降约 73%。

**未优化但记录**：

- 导入 `import_commit` 每行独立事务（单行失败不阻断其他行），500 行约 11 s；若需更快可改分批事务，但会改变“单行失败隔离”语义；
- 学生课表在无发布排课时返回空（3 queries），有数据时的多表 join 未单独压测。

阈值（脚本内）：列表 ≤500 ms、总览 ≤1500 ms、课表 ≤500 ms、导入提交 ≤60 s。

---

## 8. 复现命令

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

& $py manage.py test smass_workspace --settings=smass.settings_product
& $py scripts\r10_full_regression.py --json
& $py scripts\ui_visual_check_v2.py --base http://127.0.0.1:8050
& $py scripts\repo_admission_check.py
```
