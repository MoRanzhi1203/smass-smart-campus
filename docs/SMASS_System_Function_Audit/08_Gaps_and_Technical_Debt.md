# 08 问题、技术债与功能缺口

> 依据：本轮源码扫描、只读 UI 探针、产品层 40 例测试、Chromium 27 项、
> 冒烟 71 页、迁移/回滚/一致性验证、全量回归 32 套件 1800 例。
> 严重度：**P0** 身份/数据/安全/重要业务不可用；**P1** 功能不完整或跨端不闭环；
> **P2** 体验/重复/明显缺陷；**P3** 维护性与低影响。
> 本轮**未发现 P0**；以下为 P1–P3 的实际问题。

---

## P1（功能不完整 / 跨端不闭环 / 安全加固）

### P1-01 兼课辅导员的对象范围被收窄，列表可见但详情 403

| 项 | 内容 |
|---|---|
| 模块 | 教师/辅导员工作台 |
| 现象 | 教师同时被授予辅导员关系后，`scoped_student_records` 先命中 `is_counselor` 分支，**只返回负责班级学生**；其教学班学生出现在 `/teacher/students/` 列表（用 `my_students`），点详情 `/teacher/students/<pk>/` 返回 403 |
| 影响角色 | 教师 + 辅导员复合身份 |
| 影响范围 | 学生档案查看、部分审批对象校验 |
| 源码证据 | `smass_workspace/permissions.py::scoped_student_records`（counselor 分支先返回）；`services/teacher.py::my_students`（教学班集合）；`views/teacher.py::student_detail`（用 `can_access_student`） |
| 复现 | 给 `dev_teacher` 授予 counselor 关系（班级不含其教学班学生）→ 打开 `/teacher/students/<教学班学生>/` → 403 |
| 根因 | 范围函数是"互斥分支"而非"并集"；列表与详情的范围来源不同 |
| 建议 | 把教师与辅导员范围取并集：`counselor_students | teaching_students`；或在 `student_detail` 显式接受"教学班学生" |
| 是否阻断 | 否（仅复合身份场景） |

### P1-02 课表只有周模板，没有教学周/日期维度

| 项 | 内容 |
|---|---|
| 模块 | 排课与课表 |
| 现象 | `ScheduleEntry` 只有 `weekday/period`，没有起止周或具体日期；学生/教师课表无法按"第 N 教学周"筛选，也无法表达单双周/调停课 |
| 影响角色 | 学生、教师、教务 |
| 影响范围 | 课表准确性、跨周排课 |
| 源码证据 | `smass_scheduling/models.py::ScheduleEntry` 字段；`services/student.py::student_entries` 直接取全部条目；`term_week_number` 仅用于展示 |
| 复现 | 查看 `/student/timetable/`：同一张表每周重复，无周次选择 |
| 根因 | R11 设计为"周模板"，未做日期映射（技术决策文档亦承认） |
| 建议 | 增加 `week_from/week_to`（或 `ScheduleEntryDate`），课表按周过滤；导入/调课走差异审批 |
| 是否阻断 | 否（教学周排课场景受限） |

### P1-03 审批结果不写通知，学生需手动刷新

| 项 | 内容 |
|---|---|
| 模块 | 考勤请假 / 通知 |
| 现象 | `approve_leave/reject_leave` 只改 `LeaveRequest` 状态，**不调用** `workflow.services.notify`；学生通知中心收不到"请假已批准" |
| 影响角色 | 学生、教师、辅导员 |
| 源码证据 | `smass_attendance/services.py::approve_leave/reject_leave`（无 notify 调用）；`smass_workflow/services.py::notify` 存在但未被审批调用 |
| 复现 | 教师批准请假 → 学生 `/notifications/` 无新通知；仅考勤页状态变化 |
| 根因 | 通知机制与业务状态机未打通 |
| 建议 | 在审批服务成功后 `notify(record.account.login_name, ...)`，event_key 用 `leave:{pk}:approved` 幂等 |
| 是否阻断 | 否（E2E 已验证状态同步） |

### P1-04 产品入口缺失：多个已实现能力无法从三端触达

| 项 | 内容 |
|---|---|
| 模块 | 多模块 |
| 现象 | 以下能力服务层已实现、深层页可用，但产品三端无入口：<br>· 学生：选课/退课、活动签到、补签、销假、退费申请、退社、组织申请<br>· 教师：无（审批已覆盖）<br>· 管理：组织 CRUD、社团审批/任职、流程定义编辑、排课求解、数据导入向导、数据导出、账单生成/退费、党建专项 |
| 影响角色 | 学生、系统管理员 |
| 源码证据 | 见 `03_Module_Catalog_Part1/2/3` 中状态为 `IMPLEMENTED_NOT_VERIFIED` 的条目；`07§2/§4` 的"无入口"列 |
| 复现 | 学生端找不到"补签/销假"按钮；管理端组织页无"新增" |
| 根因 | 产品融合优先覆盖高频闭环，低频/复杂操作保留专业工具页 |
| 建议 | 按使用频率分批产品化；短期在页面给"前往专业工具"显式入口并说明 |
| 是否阻断 | 否（专业工具可用），但影响"完整产品"体验 |

### P1-05 安全增强模块未接入产品路径

| 项 | 内容 |
|---|---|
| 模块 | 安全 |
| 现象 | 独立实现的 MFA（`smass_mfa`）、二次认证/双人审批（`smass_stepup`）、策略引擎（`smass_policy`）、隐私最小化（`smass_privacy`）、上传安全（`smass_uploads`）、追加式审计（`smass_audit`）**未在 `settings_product` 注册**，产品端不启用；敏感操作（重置口令、角色授予、批量导入）无二次认证 |
| 影响角色 | 系统管理员及其它敏感操作者 |
| 源码证据 | `smass/settings_product.py`（INSTALLED_APPS 无上述 App）；`settings_s09/s10/s11/s13/s14/s16.py` 独立配置 |
| 复现 | 管理端重置口令/授予角色：只需一次会话，无 TOTP/再认证/双人审批 |
| 根因 | 安全模块为独立验收，产品融合未接入 |
| 建议 | 至少在 `admin.user_reset`、`admin.user_role`、导入提交前接入 step-up；MFA 可按角色灰度启用 |
| 是否阻断 | 否（功能可用），但安全等级低于独立模块的宣称 |

### P1-06 管理端"可看不可管"页面缺少原因提示

| 项 | 内容 |
|---|---|
| 模块 | 管理控制台 |
| 现象 | 组织架构、社团、流程定义、排课求解、导入导出、数据导出在管理端为只读或跳专业工具；学院管理员在多数写页面看不到按钮，但页面没有"为什么" |
| 影响角色 | 学院管理员、系统管理员 |
| 源码证据 | `07§4` 表格；模板中 `{% if is_super %}` 控制表单，无提示文案（用户账号/学籍页除外） |
| 复现 | 学院管理员打开 `/admin/academics/`：无表单，仅表格 |
| 根因 | 权限收紧优先，提示文案未同步 |
| 建议 | 只读页统一加"当前角色只读/需系统管理员"提示与申请路径 |
| 是否阻断 | 否 |

### P1-07 无后台任务与调度：探针、告警、通知、清理均需手动

| 项 | 内容 |
|---|---|
| 模块 | 运维 |
| 现象 | 无 Celery/APScheduler/cron；`ReadinessProbe`/`AlertEvent` 无自动生成；通知不推送；会话/临时数据无清理任务 |
| 影响角色 | 运维、管理员 |
| 源码证据 | 全仓无 celery/redis/rq；`settings.CACHES=LocMemCache`；`smass_operations` 只有模型与中间件 |
| 复现 | `/admin/monitoring/` 探针/告警在长时间无人工触发时为空 |
| 根因 | 单机开发形态，未引入任务框架 |
| 建议 | 生产部署前引入调度（cron/APScheduler）或外部监控；至少提供 `manage.py` 探针命令 |
| 是否阻断 | 否（开发/演示可用） |

### P1-08 两套认证入口并存，误启动会回到旧系统

| 项 | 内容 |
|---|---|
| 模块 | 部署 |
| 现象 | `smass.settings`（旧 app01 三表 + `smass.urls`）与 `smass.settings_product`（统一账号）同时存在；若运维用默认 `manage.py runserver` 启动，会进入旧系统，账号体系与产品数据不一致 |
| 影响角色 | 运维、全部用户 |
| 源码证据 | `smass/settings.py`（默认）、`smass/urls.py`；`smass/settings_product.py` |
| 复现 | `python manage.py runserver`（不带 settings）→ 旧登录页 |
| 根因 | 为兼容历史而保留默认配置 |
| 建议 | 在 README/部署脚本显式指定 `--settings=smass.settings_product`；或将默认 settings 指向产品（需单独评审） |
| 是否阻断 | 否（按文档启动即正确） |

---

## P2（体验、重复功能、明显缺陷）

| ID | 问题 | 模块 | 现象/证据 | 影响 | 建议 |
|---|---|---|---|---|---|
| P2-01 | 两套 UI 体系并存 | 前端 | 产品 `workspace/base.html` + 自建 CSS；历史 `r10/base.html` + Bootstrap | 跳专业工具时视觉割裂 | 逐步把高频专业工具页套用统一 shell，或明确"专业工具"视觉标识 |
| P2-02 | 通知公告与通知中心重叠 | 消息 | 学生/教师端"通知公告"与"通知中心"都列公告 | 重复浏览 | 公告并入通知中心，保留"仅公告"筛选 |
| P2-03 | 审批驳回无理由输入 | 审批 | `/teacher/approvals/` 驳回按钮直接提交，服务用默认理由 | 审批质量 | 增加理由输入（modal 或行内） |
| P2-04 | 列表无分页 | 管理端 | 用户 200、审计 80、登录 40 条上限，无分页/筛选 | 大数据不可用 | 加分页与服务端筛选 |
| P2-05 | 学籍双份身份字段 | 学籍 | `StudentProfile` 与 `StudentRecord` 都存姓名/学院/班级 | 不一致风险 | 明确权威源（建议 StudentRecord.unit + Account），Profile 只读派生 |
| P2-06 | 通知 recipient 为字符串 | 通知 | `Notification.recipient = login_name`，改名/删号不级联 | 历史通知孤立 | 增 FK 或迁移时同步 |
| P2-07 | 学院管理员深层页可能按 RBAC 放行 | 权限 | R4/R5 深层视图用 `add/change` 权限（学院管理员有），产品页却 `require_system_admin` | 同角色不同入口能力不一致 | 统一以服务层/守卫为准，或收紧 RBAC 矩阵 |
| P2-08 | 总览无时间筛选/缓存 | 统计 | `/admin/` 实时聚合多表 | 数据量大时慢 | 加时间窗与快照 |
| P2-09 | 课表 JSON 端点未在产品使用 | 排课 | `/r11/timetable/mine.json` 存在但产品页不调用 | 冗余 | 保留给第三方/移动端，文档标注 |
| P2-10 | 教师端教学班无导出 | 教学 | 仅列表 | 教师需要 Excel | 复用 S25 导出 |

---

## P3（维护性、命名、文档）

| ID | 问题 | 证据 | 建议 |
|---|---|---|---|
| P3-01 | 命名体系混杂（`app01`、`r21`、`smass_*`、`settings_r*`） | 仓库结构 | 新代码统一 `smass_*`；旧名保留（不改历史） |
| P3-02 | 144 个视图函数未被产品 URL 引用 | `inventory/supplement.json::unreferenced_view_functions` | 标注为独立配置页面；定期清理死代码 |
| P3-03 | 模型缺少统一 `created_by/updated_by` | 各模型 | 审计字段按需补充，不做全量改造 |
| P3-04 | 历史版本号出现在文档/路径（R4/R10/R20） | `docs/` 与 URL 前缀 | 用户界面已不出现；文档保留作溯源 |
| P3-05 | 测试脚本重复（`r10_full_regression` 与 `product_*`） | `scripts/` | 产品脚本纳入回归或统一入口，避免双维护 |
| P3-06 | 默认 `settings.py` 易误启动 | 同 P1-08 | 部署脚本显式指定 settings |
| P3-07 | 部分模型无历史/审计表 | 如 `AcademicYear`、`Room` | 变更频率低的模型可接受；高价值模型补审计 |
| P3-08 | `StudentProfile` 反向访问器命名 `student_profile` 易误用 | `Account.student_profile` | 文档标注；代码评审检查 |

---

## 严重度统计

| 严重度 | 数量 | 说明 |
|---|---|---|
| P0 | 0 | 未发现身份/数据/安全/核心业务完全不可用 |
| P1 | 8 | 复合身份范围、课表周次、审批通知、入口缺失、安全未接入、只读提示、无调度、双入口 |
| P2 | 10 | UI 两套、通知重叠、驳回理由、分页、双份字段、通知字符串、RBAC 不一致、总览性能、JSON 冗余、导出缺失 |
| P3 | 8 | 命名、死代码、审计字段、版本号、脚本重复、默认配置、审计表、命名易误用 |
| **合计** | **26** | |

> 以上均为本轮实际发现；未把"设计上的只读"（如学院管理员不能改系统配置）
> 计为缺陷，只在 P1-06 记录"缺少原因提示"的体验问题。
