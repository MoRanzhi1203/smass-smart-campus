# 05 管理控制台方案与现状

> 入口 `/admin/`；系统管理员全局，学院管理员受限。

---

## 1. 页面与能力现状

| 页面 | URL | V2.0 能力 | 状态 |
|---|---|---|---|
| 控制台总览 | `/admin/` | 指标、请求、健康、告警 | 已有 |
| 用户账号 | `/admin/users/` | 创建、授/撤角色、停用、重置；**分页** | IMPLEMENTED |
| 角色与权限 | `/admin/roles/` | 角色矩阵 | 已有（只读） |
| 组织架构 | `/admin/organizations/` | **新建/改名/移动/停用启用**（E01） | IMPLEMENTED |
| 教师档案 | `/admin/teachers/` | **列表/新建账号+档案/编辑**（E02） | IMPLEMENTED |
| 学籍管理 | `/admin/records/` | 筛选、详情、编辑；**分页** | IMPLEMENTED |
| 学籍异动 | `/admin/record-changes/` | 转专业/状态审批 | 已有 |
| 学年学期与课程 | `/admin/academics/` | 创建学年/学期/课程 | 已有 |
| 教学班与选课 | `/admin/sections/` | 建班、名单 | 已有 |
| 排课与课表 | `/admin/scheduling/` | **创建批次/求解/冲突/发布**（E03） | IMPLEMENTED |
| 教室与场地 | `/admin/facilities/` | 台账、建场地 | 已有 |
| 预约审批 | `/admin/booking-approvals/` | 批准/驳回 | 已有 |
| 待办与审批 | `/admin/approvals/` | 任务完成 | 已有 |
| 流程定义 | `/admin/workflows/` | **新建发布流程/发起实例**（E04） | IMPLEMENTED |
| 活动管理 | `/admin/activities/` | 创建/发布/结束/生成学分 + **学分认定**（E05） | IMPLEMENTED |
| 社团与学生组织 | `/admin/clubs/` | **入社审批/任命/卸任**（E05） | IMPLEMENTED |
| 财务与账单 | `/admin/finance/` | **收费项/账单生成/退费审批**（E06） | IMPLEMENTED |
| 通知公告 | `/admin/notices/` | 创建/发布 | 已有 |
| 数据导入导出 | `/admin/data-exchange/` | **CSV 预检/提交/历史**（E07） | IMPLEMENTED |
| 运行监控 | `/admin/monitoring/` | 请求、探针、告警 | 已有 |
| 安全审计 | `/admin/audit/` | 操作日志/登录尝试；**分页** | IMPLEMENTED |
| 系统配置 | `/admin/settings/` | 动作、字段策略、密码策略 | 已有（只读） |

---

## 2. 管理端不再依赖专业工具的核心操作

| 能力 | 之前 | 现在 |
|---|---|---|
| 组织增改移停 | 必须 `/r4/units/` | `/admin/organizations/` |
| 教师档案 | 无入口 | `/admin/teachers/` |
| 排课求解发布 | 必须 `/r11/plan/` | `/admin/scheduling/` |
| 流程创建与发起 | 必须 `/r6/` | `/admin/workflows/` |
| 入社审批/任职 | 必须 `/r15/` | `/admin/clubs/` |
| 学分认定 | 必须 `/r14/credits/` | `/admin/activities/` |
| 收费项/账单/退费 | 必须 `/r18/` | `/admin/finance/` |
| CSV 导入 | 必须 `/r4/import/` | `/admin/data-exchange/` |

仍保留专业工具入口（字段级配置、复杂多级流程、导出、排课需求编辑）。

---

## 3. 明确未完成

| 项 | 说明 |
|---|---|
| 导出产品化 | 导出仍走 S25 专业工具，需补字段裁剪与权限 |
| 数据质量页 | R7 有模型，管理端无页面 |
| 报表筛选 | 指标/报表页未产品化 |
| 多级流程编辑 | 仅单级审批模板，节点编辑仍在 `/r6/` |
| 字段级策略编辑 | 只读展示 |

---

## 4. 证据

- 产品层：`AdminOrganizationTests`、`AdminTeacherTests`、`AdminSchedulingTests`、`AdminWorkflowTests`、`AdminClubManagementTests`、`AdminCreditTests`、`AdminFinanceTests`、`AdminDataImportTests`、`AdminPaginationTests`；
- 视觉：`.local/evidence/v2/phase/admin-*.png`。
