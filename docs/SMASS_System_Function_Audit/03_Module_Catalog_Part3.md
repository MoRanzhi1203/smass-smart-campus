# 03 模块功能目录 · Part 3

> 覆盖模块 17–23：专项组织、数据交换、分析、通知、运维、安全、app01 未覆盖。

---

## 模块 17：组织专项业务（党建/专项组织）

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 党建与专项组织 |
| 业务目标 | 分级敏感的组织、成员、活动、文档与受控访问 |
| 面向账号 | 授权用户（`AccessGrant`）、系统管理员 |
| 代码位置 | `smass_party/`（7 模型 + services + views） |
| 原始来源 | R19 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M17-F01 | 组织列表/详情 | 授权用户 | `/r19/orgs/`、`/r19/orgs/<pk>/` | PartyOrg | 敏感级别 | 只读 | R19 35 例 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |
| M17-F02 | 创建组织 | 管理员 | `/r19/orgs/create/` | PartyOrg | 编码唯一 | 新增 | R19 测试 | IMPLEMENTED_NOT_VERIFIED |
| M17-F03 | 成员管理 | 管理员 | `/r19/orgs/<pk>/members/add/` | PartyMember | 学生/组织 | 新增 | R19 测试 | IMPLEMENTED_NOT_VERIFIED |
| M17-F04 | 组织活动 | 管理员 | `/r19/orgs/<pk>/activities/add/` | PartyActivity | 日期/类型 | 新增→完成 | R19 测试 | IMPLEMENTED_NOT_VERIFIED |
| M17-F05 | 文档与密级 | 管理员 | `/r19/orgs/<pk>/documents/add/`、`/r19/documents/<pk>/` | PartyDocument | 密级/授权 | 新增 | R19 测试 | IMPLEMENTED_NOT_VERIFIED |
| M17-F06 | 访问申请/授权 | 用户/管理员 | `/r19/access/` | AccessRequest/AccessGrant | 密级/有效期 | pending→granted | R19 测试 | IMPLEMENTED_NOT_VERIFIED |
| M17-F07 | 访问日志 | 管理员 | `/r19/audit/` | AccessLog | 只读 | 追加 | R19 测试 | IMPLEMENTED_NOT_VERIFIED |

### C. 页面说明

`/r19/orgs/`：组织卡/列表、成员、活动、文档、访问申请；敏感文档按 `AccessGrant.level`
过滤；产品三端**没有入口**（导航未包含，管理端也未链接）。

### D. 后端业务规则

- 文档访问：`AccessGrant`（level + 有效期 + 未撤销）+ `AccessRequest` 审批。
- 所有访问写 `AccessLog`（谁、哪份、动作、用途、IP）。
- 拒绝：无授权 → 空集/403；过期授权失效。

### E. 验证状态

`IMPLEMENTED_NOT_VERIFIED`：R19 独立测试 35 例通过，但产品路径未接入，
本轮未做产品内浏览器验证。

---

## 模块 18：数据导入、导出与模板

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 数据交换 |
| 业务目标 | 统一模板、预检（零写入）、提交（重新校验）、导出与公式注入防护 |
| 面向账号 | 管理员（导入/导出） |
| 代码位置 | `smass_data_exchange/`（schema/adapters/parsing/service/export）、`smass_organization.import_*` |
| 原始来源 | S25 + S25-R4/R5 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M18-F01 | 数据集清单 | 管理员 | `/admin/data-exchange/` · `admin.data_exchange` | 无（schema 注册表） | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M18-F02 | 模板下载 | 管理员 | `/r4/import/`（模板接口） | DataImportJob | 版本化 schema | 无 | S25 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M18-F03 | 上传预检 | 管理员 | `/r4/import/preview/` | DataImportJob/RowError | 类型/魔数/大小/行数 | 零写入 | S25 85 例 | IMPLEMENTED_AND_VERIFIED |
| M18-F04 | 提交导入 | 管理员 | `/r4/import/commit/` | 各业务表 | 重新解析校验 | 批次成功/失败 | S25 测试 | IMPLEMENTED_AND_VERIFIED |
| M18-F05 | 行级错误反馈 | 管理员 | 预检/结果页 | DataImportRowError | 行号/列/错误码 | 记录 | S25 测试 | IMPLEMENTED_AND_VERIFIED |
| M18-F06 | 学生导出 | 管理员 | `/r4/students/export/` | StudentRecord | 字段裁剪/掩码 | 只读 | R4 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M18-F07 | 报表导出 | 管理员 | `/r7/reports/<code>/export/` | ReportRun | 字段/公式中和 | 只读 | R7 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M18-F08 | 幂等 | — | 服务层 | 业务唯一约束 | 重复提交 skip | — | S25 测试 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/admin/data-exchange/` | 数据集表（编码/名称/版本/字段数）+ 导入/教务按钮 | 查看；进专业工具 | 「暂无可用数据集」 |
| `/r4/import/` | 上传、预检摘要、提交、错误表 | 上传/预检/提交 | 无文件提示 |

### D. 后端业务规则

- `Schema`：字段 code 唯一、enum 必须有 choices；模板由 schema 生成。
- 预检零写入；令牌绑定文件 SHA256 + schema 版本 + 操作者 + 30 分钟有效期。
- 提交重新解析、重新校验；有错误默认整体拒绝；唯一约束兜底幂等。
- 文件安全：类型白名单、魔数、压缩炸弹上限、8MB/5000 行、`data_only=True`。
- 导出：字段级裁剪 + 公式注入中和（`= + - @` 开头加单引号）+ 敏感掩码。

### E. 验证状态

`IMPLEMENTED_AND_VERIFIED`（S25 85 例 + 产品清单页）；
产品只提供清单与入口，实际导入走 `/r4/import/`。

---

## 模块 19：统计分析与报表

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 指标与报表 |
| 业务目标 | 指标定义/快照、报表运行、数据质量；管理端总览统计 |
| 面向账号 | 管理员（按 `permission_roles`）、系统管理员 |
| 代码位置 | `smass_analytics/`（5 模型）、`smass_operations`（请求指标）；产品 `admin.home` |
| 原始来源 | R7 + 产品聚合 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M19-F01 | 指标看板 | 管理员 | `/r7/dashboard/` | MetricDefinition/Snapshot | 角色可见 | 只读 | R7 31 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M19-F02 | 指标定义/校验 | 管理员 | `/r7/metrics/` | MetricDefinition | 口径/版本 | draft→validated | R7 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M19-F03 | 报表运行/详情 | 管理员 | `/r7/reports/<code>/` | ReportDefinition/Run | 角色/口径 | running→done | R7 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M19-F04 | 报表导出 | 管理员 | `/r7/reports/<code>/export/` | ReportRun | 字段/公式 | 只读 | R7 测试 | IMPLEMENTED_AND_VERIFIED |
| M19-F05 | 数据质量问题 | 管理员 | 数据层 | DataQualityIssue | 只读 | 追加 | R7 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |
| M19-F06 | 管理端总览统计 | 管理员 | `/admin/` | 多模型聚合 | 范围 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M19-F07 | 请求指标 | 管理员 | `/admin/monitoring/` | RequestMetric | 24h 窗口 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

`/admin/`：账号/学籍/教学/排课/待办/预约/活动/费用 8 卡 + 近 24h 请求表 + 健康 + 告警。
`/r7/dashboard/`：指标看板与报表（Bootstrap）。

### D. 后端业务规则

- 指标：`permission_roles` 允许列表；快照按 `scope_hash/query_hash` 去重。
- 报表：运行记录 `rows` JSON；导出走 S25 导出器（公式中和）。
- 产品总览为实时聚合，不做缓存（单库小数据量可接受）。

### E. 验证状态

产品总览 `IMPLEMENTED_AND_VERIFIED`；R7 指标/报表
`IMPLEMENTED_AND_VERIFIED`（专业工具，31 例）。

---

## 模块 20：消息通知

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 通知 |
| 业务目标 | 站内通知（定向到人）+ 公告（按受众）+ 统一通知中心 |
| 面向账号 | 全部 |
| 代码位置 | `smass_workflow.models.Notification`、`smass_forum.models.Announcement`、`smass_portal.PortalNotice`；产品 `common.notifications` |
| 原始来源 | R6 通知 + R17 公告 + 产品合并 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M20-F01 | 站内通知生成 | 服务层 | `workflow.services.notify` | Notification | event_key 幂等 | 新增 | R6 测试 | IMPLEMENTED_AND_VERIFIED |
| M20-F02 | 通知中心 | 全部 | `/notifications/` | Notification/Announcement | 登录 | 打开即已读 | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M20-F03 | 公告合并 | 全部 | 同上 | Announcement | audience | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M20-F04 | 未读角标 | 全部 | `base.html` | Notification | recipient | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M20-F05 | 消息中心（R6） | 管理员 | `/r6/notifications/` | Notification | recipient | 已读 | R6 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M20-F06 | 门户公告 | 全部 | `/r20/`、`/r20/admin/notice/` | PortalNotice | 角色 | draft→published | R20 36 例 | IMPLEMENTED_NOT_VERIFIED（产品无入口） |

### C. 页面说明

`/notifications/`：合并列表（来源/时间/级别/已读状态）；空状态「暂无通知」；
打开页面把本人未读通知标记已读（一次性 update）。

### D. 后端业务规则

- `notify(recipient, title, event_key)`：event_key 幂等，避免重复通知。
- 通知对象是 `login_name` 字符串，**不是 FK**；改名/删除账号不会级联清理。
- 公告：`status=published` 才展示；audience ∈ all/student/teacher。

### E. 验证状态

`IMPLEMENTED_AND_VERIFIED`（产品通知中心 + R6 深层）。

---

## 模块 21：系统配置、运维、监控与健康检查

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 运维与配置 |
| 业务目标 | 请求指标、慢请求、探针、告警；系统配置与权限治理视图 |
| 面向账号 | 管理员（读）、系统管理员（配置） |
| 代码位置 | `smass_operations/`、`smass_workspace/views/admin.py`、`settings_product.py` |
| 原始来源 | R8/R9 + 产品 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M21-F01 | 请求指标采集中间件 | 全部 | `RequestMetricsMiddleware` | RequestMetric | 排除静态 | 追加 | 中间件 | IMPLEMENTED_AND_VERIFIED |
| M21-F02 | 运行监控页 | 管理员 | `/admin/monitoring/` | RequestMetric/Probe/Alert | 24h | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M21-F03 | 就绪探针 | 系统 | `/r9/status/` | ReadinessProbe | 只读 | 追加 | R9 测试 | IMPLEMENTED_AND_VERIFIED |
| M21-F04 | 告警规则/事件 | 管理员 | `/admin/monitoring/` | AlertRule/AlertEvent | 阈值/窗口 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M21-F05 | 系统配置视图 | 系统管理员 | `/admin/settings/` | 授权动作/字段策略/密码策略 | 只读 | 只读 | 产品 E2E | IMPLEMENTED_AND_VERIFIED |
| M21-F06 | 配置修改 | 运维 | 环境变量/`settings_product.py` | — | — | 重启生效 | 文档 | IMPLEMENTED_NOT_VERIFIED（无 UI，设计如此） |
| M21-F07 | 健康检查 | 系统 | `/r9/status/` | Probe | 只读 | — | R9 测试 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

`/admin/monitoring/`：4 统计、最慢请求、探针、告警、规则；
空状态「暂无请求指标」「暂无探针记录」。
`/admin/settings/`：动作权限 chips、角色账号数、字段策略表、密码策略。

### D. 后端业务规则

- `RequestMetricsMiddleware`：记录 method/route/status/duration；静态资源跳过（实测有跳过逻辑）。
- 探针为独立命令/测试触发，非定时任务（无调度器）。
- 配置只读展示；修改须改环境变量并重启（避免运行期篡改安全策略）。

### E. 验证状态

`IMPLEMENTED_AND_VERIFIED`；配置修改为设计上的非 UI 能力。

---

## 模块 22：安全审计、备份、权限与灾难恢复

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 安全与运维治理 |
| 业务目标 | 审计追溯、备份恢复演练、权限治理、敏感信息防护 |
| 面向账号 | 管理员（审计读）、系统管理员（配置） |
| 代码位置 | `r21_account`（AuditLog/LoginAttempt）、`smass_audit`（独立）、`scripts/`（备份/指纹/演练） |
| 原始来源 | S16/S21/S22 + 产品 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M22-F01 | 账号审计日志 | 管理员 | `/admin/audit/` | AccountAuditLog | 只读 | 追加 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M22-F02 | 登录尝试审计 | 管理员 | `/admin/audit/` | LoginAttempt | 只读 | 追加 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M22-F03 | 追加式审计/告警 | 系统管理员 | `/s16/`（独立） | 独立模型 | — | 追加 | S16 20 例 | IMPLEMENTED_NOT_VERIFIED（产品未接入） |
| M22-F04 | 备份/恢复演练 | 运维 | `scripts/`（S22 脚本） | — | RPO/RTO | — | S22 演练 PASS | IMPLEMENTED_AND_VERIFIED（脚本，非产品 UI） |
| M22-F05 | 正式库指纹 | 审计 | `scripts/db_fingerprint.py` | — | 只读 | — | 指纹一致 | IMPLEMENTED_AND_VERIFIED |
| M22-F06 | MFA / 二次认证 / 双人审批 | 系统管理员 | `/s09/`、`/s10/`（独立） | 独立模型 | TOTP/审批 | — | 24+26 例 | IMPLEMENTED_NOT_VERIFIED（产品未接入） |
| M22-F07 | 权限矩阵/字段策略 | 系统管理员 | `/admin/settings/` | Permission/StudentFieldDefinition | 只读 | — | 产品 E2E | IMPLEMENTED_AND_VERIFIED |
| M22-F08 | 敏感响应防缓存 | 全部 | `SensitiveResponseMiddleware` | — | — | no-store | 中间件 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

`/admin/audit/`：账号操作日志（时间/动作/操作者/目标/说明/IP）+ 登录尝试（成功/失败）。
空状态「暂无审计日志」「暂无登录记录」。

### D. 后端业务规则

- 审计只记录操作者/动作/对象标识，不记录密码/哈希/完整身份证。
- 指纹脚本只读；恢复演练在隔离库进行，不碰正式库。
- **重要缺口**：MFA/step-up/双人审批未注册到产品配置，三端敏感操作
  （重置口令、角色授予、批量导入）**没有**二次认证或双人审批。

### E. 验证状态

产品审计 `IMPLEMENTED_AND_VERIFIED`；备份/指纹 `IMPLEMENTED_AND_VERIFIED`（脚本）；
高级安全机制 `IMPLEMENTED_NOT_VERIFIED`（独立测试通过，产品未接入）。

---

## 模块 23：app01 中尚未被产品完全覆盖的功能

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 历史系统遗留功能 |
| 业务目标 | 盘点 app01 仍存在但产品未覆盖的能力，避免"迁移后功能丢失"误判 |
| 面向账号 | 历史管理员（旧入口） |
| 代码位置 | `app01/`（18 模型、84 视图函数）、`templates/admin`、`templates/login` |
| 原始来源 | app01 |

### B. 功能清单

| ID | 功能 | 产品是否覆盖 | 说明 | 状态 |
|---|---|---|---|---|
| M23-F01 | 管理员账号 CRUD | 部分 | 产品可创建/授权/停用/重置；旧页有独立 CRUD | PARTIALLY_IMPLEMENTED |
| M23-F02 | 学生档案 CRUD + Excel 导入 | 部分 | 产品只读 + 编辑；导入走 S25；旧页有完整 CRUD | PARTIALLY_IMPLEMENTED |
| M23-F03 | 教师档案 CRUD | **未覆盖** | R21 只有 TeacherProfile 读取；旧页有教师 CRUD | NOT_IMPLEMENTED（产品） |
| M23-F04 | 班级/学院/专业/年级 CRUD | 部分 | R4 组织树覆盖；旧页仍在 | PARTIALLY_IMPLEMENTED |
| M23-F05 | 部门/团学干部/班委管理 | **未覆盖** | 迁移只写组织关系；产品无管理界面 | NOT_IMPLEMENTED（产品） |
| M23-F06 | 楼栋/寝室台账 | **未覆盖** | 产品只读学生住宿；无楼栋/寝室管理 | NOT_IMPLEMENTED（产品） |
| M23-F07 | 民族/职务字典 | **未覆盖** | app01 Nation/Position 表；产品未使用 | NOT_IMPLEMENTED（产品） |
| M23-F08 | 旧登录入口（三角色分页） | 被统一登录替代 | `/login/` 统一；旧 `/login/account/*` 未挂载产品 | NOT_APPLICABLE（产品） |
| M23-F09 | 旧后台报表/导出 | 部分 | S25/R7 有导出；旧页仍在 | PARTIALLY_IMPLEMENTED |
| M23-F10 | 旧 MD5 密码兼容 | 迁移继承哈希 | 旧账号可登录（PBKDF2）；MD5 需改密 | IMPLEMENTED_AND_VERIFIED（迁移） |

### C. 页面说明

`app01` 的 84 个视图函数与 `templates/admin/*`、`templates/student/*`、`templates/teacher/*`
**未挂载到 `urls_product`**（产品只 include `urls_r10` 与 R11–R20）。
因此产品用户看不到旧后台；旧功能通过 `settings.py` + `smass.urls` 仍可运行（独立入口）。

### D. 后端业务规则

- 旧 `app01` 认证使用 `session['info']`（`id/type/name`），与 R21 账号体系**不互通**。
- 迁移脚本把旧学生/教师/管理员映射为 R21 账号；旧表保留不删。
- **风险**：两套认证入口并存（产品 `/login/` 与旧 `smass.urls` 的 `/login/` 取决于配置），
  运维必须明确只部署产品配置。

### E. 验证状态

`PARTIALLY_IMPLEMENTED`：核心身份/学籍/教务已迁移并被产品覆盖；
教师档案、班委/团学、寝室台账、字典表未产品化（见 08 缺口）。
