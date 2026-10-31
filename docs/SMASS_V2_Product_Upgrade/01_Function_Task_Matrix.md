# 01 功能任务矩阵

> 状态：`TODO` / `IN_PROGRESS` / `IMPLEMENTED` / `VERIFIED` / `BLOCKED`
> `VERIFIED` 必须有：代码改动 + 测试证据 + 页面证据（必要时截图）。
> 审计映射：`docs/SMASS_System_Function_Audit/` 的功能 ID / 问题 ID。

---

## 状态快照（V2.0 收尾）

| 项 | 值 |
|---|---|
| 产品层测试 | **142 例**（`smass_workspace`） |
| 全量回归 | 32 套件 / **1902 例** / 0 失败（交付回归 `regression_delivery.log`） |
| 视觉 | 明色 204 项 + 暗色 68 项，0 溢出 |
| 无障碍 | 明/暗各 11 页 0 问题 |
| 已知遗留 | B05 的 DataTable/Modal/Toast 未抽象；D 的名单导出与班级考勤统计页未做 |
| 分层说明 | A02 经试点判定保持“产品入口策略 + 深层业务语义”分层，不属于越权缺陷 |

---

## A 安全与数据一致性

| ID | 任务 | 审计映射 | 缺口 | 状态 | 证据 |
|---|---|---|---|---|---|
| A01 | 兼课辅导员对象范围（教学班 ∪ 负责班级） | M5-F03/F04、P1-01 | P1-01 | **VERIFIED** | `permissions.teacher_scope_students`；`teacher.py::students`；4 例新测试（46 例全绿） |
| A02 | 统一 RBAC 与业务守卫 | P2-07、M2-F09 | P2-07 | **已审计 + 试点结论：不收紧** | `rbac_consistency_check.py`：35 处产品守卫 / 28 处深层 `has_action`；试点把 activities/clubs 的 `MANAGER_ROLES` 去掉 `teacher` → R14 立即 22 errors（教师无法发起活动），已回滚。结论：产品端“仅系统管理员”是入口策略，深层“教师/学院管理员可管”是业务语义，二者是分层差异而非权限漏洞；不做破坏性统一 |
| A03 | 敏感操作安全（MFA/step-up/审计接入） | M22-F06、P1-05 | P1-05 | **IMPLEMENTED（退费双人审批 + MFA）** | 二次口令（重置/授权/导入）；MFA 已接入（默认关闭，env 开启）；**退费双人审批**：`reviewed` 状态 + 复核人/批准人互斥 + 申请人不可批；3 例测试（双人流程、同人拒绝、跳过复核拒绝） |
| A04 | 数据权威源（Profile/Record/Notification） | 02_Model_Consolidation | P2-05/P2-06 | **IMPLEMENTED** | 通知外键 + 回填；`StudentRecord` 保存时同步 `StudentProfile` 姓名/学号（超长跳过，防截断）；数据质量页 5 类检查；6 例测试（外键写入/旧字符串可见/改名可见；同步、质量不再报不一致、超长跳过）；R4 72 例、R5 56 例回归通过 |

---

## B UI 设计系统

| ID | 任务 | 状态 | 证据 |
|---|---|---|---|
| B01 | 视觉方向（Modern Campus SaaS） | IMPLEMENTED | `app.css` 顶部注释与令牌 |
| B02 | 设计令牌统一（品牌/语义/间距/圆角） | **VERIFIED** | `:root` 全量令牌；12 视口截图 |
| B03 | 布局基线（顶栏 62、侧栏 248、内边距 24–28） | IMPLEMENTED | 折叠侧栏未实现 |
| B04 | 字体与图标（系统字体栈 + 19 个线性 SVG） | IMPLEMENTED | `base.html` symbols |
| B05 | 组件体系（AppShell/Header/Sidebar/PageHeader/StatCard/DataTable/FilterBar/Pagination/Modal/…） | **部分完成** | `_empty_state.html`（6 处）、`_pagination.html`（3 列表）、`badges.badge_class` 过滤器（账单/报名/社团 4 处）；DataTable/Modal/Toast/Tabs 未统一 | 无 |
| B06 | 暗色模式 | **IMPLEMENTED** | `prefers-color-scheme: dark` 覆盖 `--ws-*` 令牌 + 三端强调色；9 处硬编码白底改 `var(--ws-surface)`；暗色快速视觉 68 项 0 溢出、11 页 a11y 0 问题（含主按钮对比度）；未做手动主题切换 |

---

## C 学生端闭环

| ID | 任务 | 审计映射 | 状态 | 说明 |
|---|---|---|---|---|
| C01 | 选课/退课 | M7、P1-04 | **IMPLEMENTED** | `available_sections`/`enroll_for_student`；`/student/courses/` 可选课程表 + 选课/退选；**时间冲突检测**（基于已发布排课，同槽即冲突）；4 + 3 例测试（成功/容量满/退课/越权、冲突检出/异槽放行/选课被拒） |
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
| D01 | 今日课程/教学班/名单/导出/周次 | M5、M8 | **IMPLEMENTED** | 教学班名单、名单导出（CSV 白名单+注入中和）、课表周次（F01） |
| D02 | 批量登记/缺勤/补签审批/统计 | M9 | **IMPLEMENTED** | 考勤详情页改为整表批量保存（一次提交全部学生）；对象级校验（非本班教师拒绝）；2 例测试；补签审批与结束考勤复用 R13 服务 |
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
| E07 | 数据导入导出产品化 | M18 | **IMPLEMENTED** | 上传预检（零写入、错误明细）、提交（重新校验、临时文件清理）、导入历史；**受控导出**（学籍/账单/账号 CSV，字段白名单 + 公式注入中和 + 审计日志）；6 例测试（预检+提交、缺列、越权、导出内容、注入中和） |
| E08 | 统计筛选/分页/监控/审计查询 | M19/M21 | **IMPLEMENTED（分页与筛选）** | 通用分页服务与组件；用户/学籍/审计三列表服务端分页（保留筛选、越界回落）；3 例测试；数据质量页与报表筛选待补 |

---

## F 联动/性能/无障碍

| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| F01 | 教学周/单双周/调停课 | **IMPLEMENTED** | `ScheduleEntry` week_from/week_to/week_pattern（迁移 0002）+ `ScheduleException`（迁移 0003，停课/调课，唯一约束 section+date+kind）；学生/教师课表按周过滤并显示“今日调停课”；管理端可登记；6 例测试（单双周、周次、查询回落、登记、学生提示、越权 403） |
| F02 | 业务事件通知（幂等 event_key） | **IMPLEMENTED（7/7 类）** | 已接入：请假、补签、场地、社团、**活动报名/候补**、**排课发布（任课教师）**、**公告发布（按受众）**；`notify_account` + 事件键幂等；通知失败不影响主业务 |
| C07 | 学籍变更申请/通知已读 | **IMPLEMENTED** | 通知中心逐条/全部已读；新增 `StudentChangeRequest`（手机号/住宿/住址）提交→审批→生效，同字段去重约束；4 例测试（提交+生效、重复拒绝、驳回理由、越权 403） |
| F03 | 列表分页/搜索/排序/导出权限 | **IMPLEMENTED（分页+搜索）** | `services/pagination.py` + `_pagination.html`；用户/学籍支持关键词与状态筛选；排序与导出权限待补 |
| F04 | 受控后台任务（探针/清理/通知） | **IMPLEMENTED（命令式）** | `manage.py smass_probe` 写就绪探针（数据库/迁移/缓存/存储）；`smass_housekeeping` 默认 dry-run，`--apply` 清理过期导入临时文件/通知/登录尝试/探针；2 例测试；未引入 Celery/Redis |
| F05 | 性能（N+1/索引/聚合/慢请求） | **IMPLEMENTED（基准+一轮优化）** | `perf_baseline_v2.py` 临时库基准；用户列表 N+1（202→3 queries，199→53.6ms）；导入 500 行 preview 2.4s/commit 11s/峰值 4.2MB；索引与慢查询持续监控 |
| F06 | 键盘/焦点/标签/对比度/WCAG | **IMPLEMENTED（自研检查）** | `a11y_check_v2.py` 11 页 0 问题（按钮名/表单标签/h1/跳过导航/lang/主按钮对比度/焦点轮廓）；用户筛选补 `aria-label`；未接 axe 与屏幕阅读器实测 |

---

## 本轮新增测试

| 测试 | 内容 | 结果 |
|---|---|---|
| `test_counselor_sees_teaching_section_student` | 兼课辅导员访问教学班学生详情 | 200 |
| `test_list_merges_teaching_and_counselor_scope` | 列表同时含两类学生 | PASS |
| `test_unrelated_student_still_403` | 无关学生仍 403 | PASS |
| `test_revoked_counselor_loses_class_scope` | 撤销任职后失去班级范围 | 403 |

产品层合计 **46 例**（原 42 + 4），全部通过。
