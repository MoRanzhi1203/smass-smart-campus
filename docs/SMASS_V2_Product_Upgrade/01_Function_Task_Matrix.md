# 01 功能任务矩阵

> 状态：`TODO` / `IN_PROGRESS` / `IMPLEMENTED` / `VERIFIED` / `BLOCKED`
> `VERIFIED` 必须有：代码改动 + 测试证据 + 页面证据（必要时截图）。
> 审计映射：`docs/SMASS_System_Function_Audit/` 的功能 ID / 问题 ID。

---

## A 安全与数据一致性

| ID | 任务 | 审计映射 | 缺口 | 状态 | 证据 |
|---|---|---|---|---|---|
| A01 | 兼课辅导员对象范围（教学班 ∪ 负责班级） | M5-F03/F04、P1-01 | P1-01 | **VERIFIED** | `permissions.teacher_scope_students`；`teacher.py::students`；4 例新测试（46 例全绿） |
| A02 | 统一 RBAC 与业务守卫 | P2-07、M2-F09 | P2-07 | TODO | — |
| A03 | 敏感操作安全（MFA/step-up/审计接入） | M22-F06、P1-05 | P1-05 | TODO | — |
| A04 | 数据权威源（Profile/Record/Notification） | 02_Model_Consolidation | P2-05/P2-06 | TODO | 设计已定，代码未改 |

---

## B UI 设计系统

| ID | 任务 | 状态 | 证据 |
|---|---|---|---|
| B01 | 视觉方向（Modern Campus SaaS） | IMPLEMENTED | `app.css` 顶部注释与令牌 |
| B02 | 设计令牌统一（品牌/语义/间距/圆角） | **VERIFIED** | `:root` 全量令牌；12 视口截图 |
| B03 | 布局基线（顶栏 62、侧栏 248、内边距 24–28） | IMPLEMENTED | 折叠侧栏未实现 |
| B04 | 字体与图标（系统字体栈 + 19 个线性 SVG） | IMPLEMENTED | `base.html` symbols |
| B05 | 组件体系（AppShell/Header/Sidebar/PageHeader/StatCard/DataTable/FilterBar/Pagination/Modal/…） | IN_PROGRESS | 已有 Shell/Header/Sidebar/PageHeader/StatCard/Badge/Empty/Alert；DataTable/分页/Modal/Toast/ConfirmDialog/Tabs 待补 |
| B06 | 暗色模式 | TODO | 预留 `--smass-*`，未实现 |

---

## C 学生端闭环

| ID | 任务 | 审计映射 | 状态 | 说明 |
|---|---|---|---|---|
| C01 | 选课/退课 | M7、P1-04 | **IMPLEMENTED**（冲突检测待 F01） | `available_sections`/`enroll_for_student`；`/student/courses/` 可选课程表 + 选课/退选；4 例测试（成功/容量满/退课/越权 404）；学期/状态/重复校验复用 R5 服务 |
| C02 | 签到/补签/销假/审批通知 | M9-F02/F08/F11 | **IMPLEMENTED** | 进行中考勤签到、补签申请与记录、已批准请假销假；4 例测试；审批结果通知已接入（F02） |
| C03 | 活动详情/候补/签到/学分 | M12-F05/F08 | **IMPLEMENTED** | 新增活动详情页（信息/报名状态/候补顺位/签到）、签到视图；列表标题链入详情；3 例测试（详情/签到成功/窗口外拒绝）；学分汇总复用志愿页 |
| C04 | 社团详情/退社/任职 | M13-F03/F04 | **IMPLEMENTED** | 新增社团详情页（信息/成员/我的申请进度/我的任职/退社）、退社视图；列表标题链入详情；3 例测试（详情、申请后退社、退他人拒绝） |
| C05 | 场地签到/释放 | M14-F06 | **IMPLEMENTED** | 预约列表新增签到（approved）与释放（approved/checked_in）按钮；2 例测试（签到→释放、为他人签到被拒） |
| C06 | 账单详情/退费申请 | M16-F03/F04 | **IMPLEMENTED** | 新增账单详情页（明细/缴费记录/退费记录/退费申请）；2 例测试（退费申请提交、详情渲染）；缴费仍为校内台账 |
| C07 | 学籍变更申请/寝室/通知已读 | M4-F06、M11 | TODO | 需先补模型/约束 |

---

## D 教师端

| ID | 任务 | 审计映射 | 状态 | 说明 |
|---|---|---|---|---|
| D01 | 今日课程/教学班/名单/导出/周次 | M5、M8 | IN_PROGRESS | 周次依赖 F01 |
| D02 | 批量登记/缺勤/补签审批/统计 | M9 | **IMPLEMENTED**（统计待补） | 考勤详情页改为整表批量保存（一次提交全部学生）；对象级校验（非本班教师拒绝）；2 例测试；补签审批与结束考勤复用 R13 服务 |
| D03 | 审批分类/驳回理由/已办/历史 | M10 | **IMPLEMENTED**（历史列表待补） | 请假/补签/场地三处驳回新增必填理由输入并落库；1 例测试（驳回理由写入 + 学生端同步） |
| D04 | 辅导员扩展一致性 | A01 | **VERIFIED（范围）** | 班级活动/组织信息待补 |

---

## E 管理端

| ID | 任务 | 审计映射 | 状态 | 说明 |
|---|---|---|---|---|
| E01 | 组织 CRUD/移动/停用 | M3 | **IMPLEMENTED** | 管理端新增组织表单（类型/编码/名称/上级）、行内改名/移动/停用启用；服务层 `rename_unit`/`set_unit_status`（停用前校验下级与学籍）；4 例测试（创建/越权 403/有学籍拒绝停用/移动） |
| E02 | 教师档案 CRUD/任课/组织 | M5-F06、M23-F03 | **IMPLEMENTED**（任课分配在 E03） | 新增 `/admin/teachers/`：列表（工号/学院/任课数/账号状态）、新建（账号+档案+角色+学院关系，一次性）、行内编辑同步展示名；4 例测试（创建可登录/重复拒绝/越权 403/改名同步） |
| E03 | 排课产品化（求解/冲突/发布） | M8-F05/F06 | **IMPLEMENTED**（需求与约束编辑仍在专业工具） | 新增 `smass_scheduling/services.py`（create_run/solve_run/publish_run 门禁）、管理端创建批次/求解/发布/冲突页；4 例测试（创建+求解+发布、重复批次拒绝、草稿发布拒绝、越权 403）；复用 R11 求解器与 verify_run |
| E04 | 工作流定义/节点/实例 | M10 | **IMPLEMENTED**（节点编辑与多级流转仍在专业工具） | 新增 `smass_workflow/blueprints.py`（单级审批模板：开始→审批→结束）、管理端新建并发布流程、发起实例（自动提交生成待办）；3 例测试（创建发布、发起生成待办、越权 403） |
| E05 | 社团审批/任职/活动管理 | M12/M13 | **IMPLEMENTED** | 社团：待批入社（通过/驳回理由）、在任干部与卸任、任命表单；活动：待认定学分列表 + 认定/驳回（理由）；7 例测试（入社 4 + 学分 3） |
| E06 | 财务收费项/账单/退费 | M16 | **IMPLEMENTED** | 新增 `/admin/finance/` 与导航：收费项创建、账单生成（学号+收费项+截止）、待批退费批准/驳回（理由）；4 例测试；仍为校内台账，未接真实支付 |
| E07 | 数据导入导出产品化 | M18 | **IMPLEMENTED**（CSV 导入；导出仍走专业工具） | 管理端新增上传预检页（零写入、错误明细、可提交/不可提交）与提交（重新校验、临时文件清理）、导入历史表；3 例测试（预检+提交落库、缺列报错、越权 403）；复用 organization.import_preview/import_commit |
| E08 | 统计筛选/分页/监控/审计查询 | M19/M21 | TODO | — |

---

## F 联动/性能/无障碍

| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| F01 | 教学周/单双周/调停课 | TODO | 需改 `ScheduleEntry` + 迁移 |
| F02 | 业务事件通知（幂等 event_key） | **IMPLEMENTED（4/7 类）** | 已接入：请假批准/驳回、补签通过/驳回、场地预约批准/驳回、社团入社通过；`notify_account` + 事件键幂等；活动/排课/公告待补 |
| F03 | 列表分页/搜索/排序/导出权限 | TODO | 管理端列表当前有上限 |
| F04 | 受控后台任务（探针/清理/通知） | TODO | 不引入分布式设施 |
| F05 | 性能（N+1/索引/聚合/慢请求） | TODO | 需基准数据 |
| F06 | 键盘/焦点/标签/对比度/WCAG | IN_PROGRESS | focus-visible 已统一；扫描未接入产品 |

---

## 本轮新增测试

| 测试 | 内容 | 结果 |
|---|---|---|
| `test_counselor_sees_teaching_section_student` | 兼课辅导员访问教学班学生详情 | 200 |
| `test_list_merges_teaching_and_counselor_scope` | 列表同时含两类学生 | PASS |
| `test_unrelated_student_still_403` | 无关学生仍 403 | PASS |
| `test_revoked_counselor_loses_class_scope` | 撤销任职后失去班级范围 | 403 |

产品层合计 **46 例**（原 42 + 4），全部通过。
