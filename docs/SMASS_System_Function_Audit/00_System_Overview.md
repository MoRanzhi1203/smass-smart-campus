# 00 系统总体架构

> 审计基线：Git `80c8d85da5a930c91f0c2bab9486b4344650f148`（分支 `feat/smass-r11-r20-full-campus`）
> 运行配置：`smass.settings_product` · 产品登录 `/login/`
> 审计日期：2026-10-31
> 本文所有数字来自 `scripts/audit_system_inventory.py` 的实际扫描结果
> （原始数据见 `inventory/`，统计规则见 §15）。

---

## 0. 审计基线与证据口径

| 项 | 实测值 | 来源 |
|---|---|---|
| Git HEAD | `80c8d85da5a930c91f0c2bab9486b4344650f148` | `git rev-parse HEAD` |
| 工作区 | 干净（审计开始前） | `git status` |
| Python | 3.12.16 | 运行时 |
| Django | 5.2.17 | `django.get_version()` |
| 产品配置 | `smass.settings_product` | `smass/settings_product.py` |
| URLConf | `smass.urls_product` | `settings_product.ROOT_URLCONF` |
| 产品库 | `smass_product_dev`（127 表） | 隔离库，非正式库 |
| 正式库 | `smass`（26 表 / 111 列） | 只读，审计未写入 |
| 账号表 | `r21_account_account` | `AUTH_USER_MODEL` 未改写，仍为 `auth.User` 类型但认证走自定义后端 |

> 审计只读取代码、Django 元数据与只读接口，未执行迁移、未写入任何业务表。
> 历史研发报告与账本仅作索引；本文结论以源码与实测为准。

---

## 1. 技术栈与依赖

| 组件 | 版本 | 用途 | 证据 |
|---|---|---|---|
| Python | 3.12.16 | 运行时 | `requirements.txt` 注释 + 实测 |
| Django | 5.2.17 | Web 框架 | `requirements.txt` |
| MySQL | 8.0.18 | 业务数据库 | `settings.py` DATABASES + 实测 |
| PyMySQL | >=1.1.2,<2 | MySQL 驱动（`smass/__init__.py` 兼容 shim） | `requirements.txt` |
| cryptography | >=41,<51 | MySQL 8 `caching_sha2_password` 认证 | `requirements.txt` |
| openpyxl | 3.1.5 | Excel 导入/模板/导出 | `requirements.txt` |
| Pillow | 13.0.0 | 图片处理（头像/上传） | `requirements.txt` |
| Playwright | 1.64.1（测试可选） | 浏览器 E2E | `requirements.txt` 注释 + 已安装 |
| pip-audit | 2.10.1（工具可选） | 依赖漏洞扫描 | `requirements.txt` 注释 |

**无外部服务依赖**：未发现 Celery、Redis、消息队列、对象存储或第三方 API 调用；
缓存为进程内 `LocMemCache`，文件存本地磁盘。

---

## 2. Django App 全量清单

`INSTALLED_APPS` 实际注册 **26 个** App（项目 20 + Django 内置 6）。

| # | label | 类型 | 职责 | 有效模型 |
|---|---|---|---|---|
| 1 | `app01` | 项目 | 历史系统（三表账号、组织、寝室、职务、导入、安全状态） | 18 |
| 2 | `r21_account` | 项目 | 统一账号、角色、组织关系、审计 | 7 |
| 3 | `r22_account` | 项目 | 双身份桥接（Legacy 映射校验） | 1 |
| 4 | `smass_organization` | 项目 | 组织树、学籍档案、变更历史、字段策略 | 7 |
| 5 | `smass_academic` | 项目 | 学年/学期/课程/教学班/选课 | 7 |
| 6 | `smass_scheduling` | 项目 | 节次、教师约束、排课、课表、冲突 | 9 |
| 7 | `smass_enrollment` | 项目 | 自动分班、转专业、学籍异动 | 5 |
| 8 | `smass_attendance` | 项目 | 考勤场次、考勤记录、请假、补签 | 4 |
| 9 | `smass_activities` | 项目 | 活动、报名、学分/志愿认定 | 3 |
| 10 | `smass_clubs` | 项目 | 社团、成员、任职 | 3 |
| 11 | `smass_facilities` | 项目 | 楼宇、房间、设备、资格、预约 | 8 |
| 12 | `smass_forum` | 项目 | 板块、帖子、评论、举报、公告 | 5 |
| 13 | `smass_finance` | 项目 | 收费项、账单、缴费、退费、台账 | 6 |
| 14 | `smass_party` | 项目 | 党建/专项组织、文档、访问授权 | 7 |
| 15 | `smass_portal` | 项目 | 门户分区/链接/公告（配置型） | 3 |
| 16 | `smass_workflow` | 项目 | 流程定义/实例/事件/待办/通知 | 8 |
| 17 | `smass_analytics` | 项目 | 指标、快照、报表、数据质量 | 5 |
| 18 | `smass_operations` | 项目 | 请求指标、告警、探针 | 4 |
| 19 | `smass_api` | 项目 | API 客户端、令牌、幂等 | 4 |
| 20 | `smass_workspace` | 项目 | 产品层（导航/守卫/聚合服务/三端视图） | 0 |
| 21 | `django.contrib.admin` | 内置 | 内置后台（未挂载产品 URL） | 1 |
| 22 | `django.contrib.auth` | 内置 | 权限与用户框架 | 3 |
| 23 | `django.contrib.contenttypes` | 内置 | 内容类型 | 1 |
| 24 | `django.contrib.sessions` | 内置 | 会话 | 1 |
| 25 | `django.contrib.messages` | 内置 | 闪现消息 | 0 |
| 26 | `django.contrib.staticfiles` | 内置 | 静态文件 | 0 |

> 另有 8 个仅在独立 settings 中注册、未进入产品配置的安全/测试 App：
> `smass_a11y`、`smass_api_security`、`smass_audit`、`smass_mfa`、
> `smass_policy`、`smass_privacy`、`smass_stepup`、`smass_uploads`、
> `smass_security_tests`、`smass_data_exchange`（纯库无模型）。
> 它们有独立测试与 URL（`/s09/`–`/s19/`），但**产品配置未 include**，
> 因此三端界面不暴露；这是本轮审计确认的现状，不是缺陷判定。

---

## 3. settings 配置继承关系

```
settings.py（历史默认：app01 + smass.urls，AUTH 走 app01 三表）
    └─ settings_r22.py（R22 账号切换验证）
        └─ settings_r4.py（组织/学籍）
            └─ settings_r5.py（教务）
                └─ settings_r6.py（流程）
                    └─ settings_r7.py（分析）
                        └─ settings_r8.py（API）
                            └─ settings_r9.py（运维）
                                └─ settings_r10.py（统一后台）
                                    └─ settings_integrated_dev.py（R10+R11–R20 单库）
                                        └─ settings_product.py（★ 产品配置，三端）
```

- `settings_product` 在 `integrated_dev` 基础上：库名改为 `smass_product_dev`、
  `ROOT_URLCONF='smass.urls_product'`、`LOGIN_URL='/login/'`、
  注册 `smass_workspace`、追加导航上下文处理器。
- 每个 `settings_*` 都有库名前缀硬校验，写错库名直接启动失败。
- 历史独立配置（`settings_r11`、`settings_r16`、`settings_s09` 等）保持可用，
  供各模块回归测试；产品只使用 `settings_product`。

---

## 4. URL 路由与命名空间

产品 URL 由 `smass/urls_product.py` 组装，解析后共 **305 条**具名路由。

| 前缀 | 条数 | 说明 |
|---|---|---|
| `/student/` | 20 | 学生工作台（15 页 + 操作路由） |
| `/teacher/` | 19 | 教师工作台（13 页 + 操作路由） |
| `/admin/` | 28 | 管理控制台（22 页 + 操作路由） |
| `/`、`/login/`、`/logout/`、`/profile/`、`/notifications/`、`/no-role/` | 6 | 产品入口与共用页面 |
| `/r4/`–`/r9/` | 约 70 | 历史组织/教务/流程/分析/API/运维功能页（保留） |
| `/r11/`–`/r20/` | 约 55 | 排课、学籍异动、考勤、活动、社团、场地、论坛、财务、党建、门户 |
| `/r10/`、`/hub/`、`/r21/*` | 6 | 重定向（研发外壳收敛到产品页） |
| `/api/`（smass_api） | 6 | 开放接口（独立配置启用） |
| Django 内置 | 7 | admin/auth/session 等（产品未挂载 admin.site.urls） |

命名空间：产品使用 `workspace:`（`app_name='workspace'`），
子模块 `urls_student/urls_teacher/urls_admin` 共享该命名空间；
历史模块使用各自前缀，不设命名空间。

> 路由明细见 `05_Page_and_Route_Catalog.md` 与 `inventory/urls.csv`。

---

## 5. 统一身份与认证

| 环节 | 实现 | 证据 |
|---|---|---|
| 登录入口 | `POST /login/` | `smass_workspace/views/auth.py::login_view` |
| 认证后端 | `django.contrib.auth.authenticate` + `r21_account.Account` | `settings.AUTHENTICATION_BACKENDS`（Django 默认 ModelBackend，Account 实现 `get_user`） |
| 会话 | Django session，`SESSION_COOKIE_HTTPONLY=True`、`SameSite=Lax` | `settings.py` |
| 失败限速 | `r21_account.services.login_lock_status/register_login_result` | `LoginAttempt` 表 |
| 落地 | 按角色：管理 → `/admin/`、教师 → `/teacher/`、学生 → `/student/` | `permissions.landing_url` |
| 无角色 | `/no-role/`（HTTP 403） | `common.no_role` |
| 强制改密 | `ForcePasswordChangeMiddleware` | `r21_account/middleware.py` |
| 会话安全 | `SessionSecurityMiddleware`（空闲超时/设备） | `app01/middleware/session_security.py` |
| 敏感响应 | `SensitiveResponseMiddleware`（`no-store`） | `app01/middleware/privacy.py` |

> `AUTH_USER_MODEL` **未被改写**，仍为 `auth.User`；但实际登录使用
> `r21_account.Account`（继承 `AbstractBaseUser`）。`auth.User` 表在产品库中为空。
> 这是历史决策（避免破坏 app01），在产品路径中以 `Account` 为准。

---

## 6. 授权模型

五维门面：`r21_account/authorization.py` + 产品守卫 `smass_workspace/permissions.py`。

| 维度 | 实现 | 拒绝方式 |
|---|---|---|
| 角色（RBAC） | `AccountRole` → Django Group → permission；`ACTION_PERMISSIONS` 9 个动作 | 未知动作拒绝 |
| 组织范围 | `scope_queryset` / `permissions.scoped_student_records` | 空集不等于全集 |
| 对象级 | `require_object` / `can_access_student` / 详情页显式判定 | HTTP 403 页面 |
| 字段级 | `StudentFieldDefinition` + `visible_fields/writable_fields` + 掩码 | 未列出即不可见 |
| 业务状态 | `AUTHORIZATION_TRANSITIONS` 状态机 | 未知转换拒绝 |

产品层守卫：

```python
@require_kind('student'|'teacher'|'admin')   # 未登录→/login/；无角色→403
@require_system_admin                         # 管理端系统级页面
```

对象范围（`permissions.py`）：

| 角色 | 学籍范围 |
|---|---|
| 系统管理员 | 全部 |
| 学院管理员 | `scope_college` 命中的组织子树 |
| 辅导员 | `OrganizationMembership(role='counselor')` 的班级及其学生 |
| 教师 | 本人教学班内已选课学生 |
| 学生 | 仅本人 |

字段权限：`StudentFieldDefinition.visible_roles/editable_roles` 允许列表；
身份证、手机等敏感字段在 `authorization.redact` 中掩码。

---

## 7. 五类身份的数据库关系

```
auth.User（空置）
r21_account.Account ──1:1── StudentProfile（学号/姓名/学院/班级/手机/身份证）
        │            └─1:1── TeacherProfile（工号/姓名/学院/手机）
        ├──1:N── AccountRole（role ∈ system_admin/college_admin/teacher/student）
        ├──1:N── OrganizationMembership（unit + role：teacher/counselor/class_committee/league_cadre）
        ├──1:1── LegacyAccountLink（source_table/source_pk，迁移锚点）
        ├──1:N── StudentRecord（学籍，FK account）
        ├──1:N── TeachingAssignment（任课）
        ├──1:N── Enrollment（选课）
        ├──1:N── RoomBooking（预约）
        ├──1:N── Notification（按 login_name 字符串，非 FK）
        └──1:N── AccountAuditLog（actor 字符串）

OrganizationUnit（学院/专业/年级/班级/部门，parent 自关联）
        └──1:N── StudentRecord.unit
```

> 详细字段与约束见 `04_Data_Model_Dictionary.md`。

---

## 8. 业务服务调用与数据关系

产品三端**不直接写业务表**，写操作调用各模块服务：

| 产品动作 | 调用服务 | 模型 |
|---|---|---|
| 学生请假 | `smass_attendance.services.submit_leave/cancel_leave` | `LeaveRequest` |
| 学生缴费 | `smass_finance.services.pay_bill` | `Bill`/`Payment`/`LedgerEntry` |
| 学生预约场地 | `smass_facilities.services.create_booking/cancel_booking` | `RoomBooking` |
| 学生报名活动 | `smass_activities.services.register/cancel_registration` | `ActivityRegistration` |
| 学生入社 | `smass_clubs.services.apply_join` | `ClubMembership` |
| 教师考勤 | `smass_attendance.services.create_session/teacher_mark/close_session` | `AttendanceSession`/`AttendanceRecord` |
| 教师审批 | `approve_leave/reject_leave/approve_makeup`、`approve_booking`、`complete_task` | `LeaveRequest`/`RoomBooking`/`ApprovalTask` |
| 管理端建课 | `smass_academic.services.create_year/term/course/section` | `AcademicYear` 等 |
| 管理端授权 | `r21_account.services.grant_role/revoke_role/set_temporary_password` | `Account`/`AccountRole` |
| 管理端公告 | `smass_forum.services.create_announcement/publish_announcement` | `Announcement` |
| 学籍异动 | `smass_enrollment.services.approve_transfer/approve_status_change` | `MajorTransferRequest`/`StudentStatusChange` |

因此三端与深层功能页共享同一套业务规则（冲突检测、状态机、权限）。

---

## 9. 数据库用途与隔离

| 库 | 用途 | 读写 | 表数 |
|---|---|---|---|
| `smass` | 正式库（历史 app01 数据） | **只读**；迁移脚本 `SET SESSION TRANSACTION READ ONLY` | 26 |
| `smass_product_dev` | 产品隔离库（演示 + 迁移验证） | 读写；可 `product_bootstrap.py` 重建 | 127 |
| `test_smass_product_dev` | 产品层测试库（`manage.py test` 自动创建/销毁） | 临时 | — |
| 其它 `smass_r*`/`smass_s*` | 历史模块独立测试/演示库 | 各模块自用 | — |

正式库只读是硬约束：`settings_product` 库名前缀校验、
迁移脚本只读事务、回归前后指纹比对（`b914b39c…`）。

---

## 10. 前端技术、模板继承与设计组件

| 项 | 实现 |
|---|---|
| 产品模板 | `smass_workspace/templates/workspace/*.html`（54 个） |
| 统一基座 | `workspace/base.html`（顶部栏 + 侧边栏 + 内容区 + 图标 symbol） |
| 设计系统 | `static/workspace/app.css`（约 900 行，CSS 变量切换三端强调色） |
| 交互 | `static/workspace/app.js`（抽屉、工作台切换、表单防重复提交） |
| 历史模板 | `templates/r4`–`r20`、`templates/r10/base.html`（Bootstrap 5 + `static/css/r10.css`） |
| 模板继承 | 产品页 `extends "workspace/base.html"`；历史页 `extends "r10/base.html"` |
| 组件 | `.ws-card`/`.ws-table`/`.ws-form-grid`/`.ws-badge`/`.ws-empty`/`.ws-alert`/`.ws-tabs`/`.ws-timeline`/`.ws-timetable` |
| 三端差异 | 仅 `body[data-workspace]` 的 `--ws-accent` 变量不同 |

> 两套模板体系并存：产品层（自建）与历史 r4–r20（Bootstrap）。
> 历史页只通过管理端"专业工具"入口进入，不参与产品导航。

---

## 11. 后台任务、缓存、日志、审计、文件存储

| 项 | 现状 | 证据 |
|---|---|---|
| 后台任务 | **无 Celery/队列**；无定时任务框架。`manage.py` 命令承担初始化/迁移/演练 | 全仓搜索无 celery/redis/rq |
| 缓存 | `LocMemCache`（单进程内存） | `settings.CACHES` |
| 日志 | `logs/smass.log`，RotatingFileHandler（5MB×3），`smass.audit` 通道 | `settings.LOGGING` |
| 审计 | `AccountAuditLog`、`LoginAttempt`、`WorkflowEvent`、`AccessLog`、`LedgerEntry`、`StudentRecordChange`、`EnrollmentHistory` | 各模型 |
| 请求指标 | `smass_operations.RequestMetricsMiddleware` → `RequestMetric` | 中间件 |
| 文件存储 | `MEDIA_ROOT=media/`；`private_uploads/`（gitignore） | `settings.py` |
| 静态文件 | `STATIC_ROOT=staticfiles/`；开发由 runserver 提供 | `settings.py` |
| 会话存储 | 数据库会话（`django_session`） | 默认 |

---

## 12. 第三方依赖与外部服务

- **无外部 SaaS/支付/短信/邮件集成**：缴费是校内台账登记（`Payment`/`LedgerEntry`），
  不接真实支付渠道；通知为站内 `Notification` 表，不发短信/邮件。
- **无对象存储**：媒体文件写本地 `media/`。
- **无 CDN**：静态资源随应用提供。
- **无容器化/编排文件**：仓库未发现 Dockerfile/k8s 清单（本轮扫描范围内）。

---

## 13. 模块依赖关系图

```
                    ┌─────────────────────────────┐
                    │ smass_workspace（产品层）     │
                    │ 导航 / 守卫 / 聚合服务 / 视图  │
                    └──────────────┬──────────────┘
        ┌───────────────┬──────────┼───────────┬────────────────┐
        ▼               ▼          ▼           ▼                ▼
 r21_account      smass_organization  smass_academic  smass_attendance  smass_facilities
 （身份/角色）      （组织/学籍）        （教务）        （考勤/请假）      （场地/预约）
        │               │          │           │                │
        │               ├──────────┼───────────┼────────────────┤
        │               ▼          ▼           ▼                ▼
        │         smass_scheduling smass_enrollment smass_activities smass_clubs
        │         （排课/课表）     （分班/异动）    （活动/志愿）     （社团）
        │
        ├── smass_workflow（流程/待办/通知） ── smass_forum（公告）
        ├── smass_finance（账单/缴费）
        ├── smass_party（党建专项）
        ├── smass_portal（门户配置，产品未用）
        ├── smass_analytics / smass_operations（统计/运维）
        └── smass_api（开放接口，产品未用）

 历史层：app01（三表账号/组织/寝室） ──迁移──▶ r21_account + smass_organization
 安全层：smass_mfa / smass_stepup / smass_policy / smass_privacy / smass_audit
         / smass_api_security / smass_uploads / smass_a11y（独立配置，产品未接入）
```

---

## 14. 主要数据流图

### 14.1 登录与落地

```
浏览器 → GET /login/ → workspace.login_view（渲染 login.html）
      → POST /login/ → authenticate(Account) → login(session)
      → permissions.landing_kind(Account)
          ├─ system_admin/college_admin → 302 /admin/
          ├─ teacher                     → 302 /teacher/
          ├─ student                     → 302 /student/
          └─ 无角色                      → 302 /no-role/ (403)
```

### 14.2 请假跨端同步

```
学生 /student/attendance/ → POST leave_submit
   → attendance.services.submit_leave（校验重叠/学籍状态）
   → LeaveRequest(status=submitted) + 审计日志
教师 /teacher/approvals/ → POST leave/approve
   → attendance.services.approve_leave → LeaveRequest(status=approved)
学生 /student/attendance/ 读取同一行 → 显示「已批准」
管理端 /admin/approvals/ 读取同一行 → 「请假状态」表显示同一状态
```

### 14.3 排课与课表

```
管理端 /admin/scheduling/（读 ScheduleRun）
   → 专业工具 /r11/plan/ 求解（deterministic-constructive-v1）
   → ScheduleRun(published) + ScheduleEntry（硬约束唯一索引兜底）
学生 /student/timetable/：Enrollment → requirement__section → Entry
教师 /teacher/timetable/：Entry.teacher = Account
```

### 14.4 数据导入

```
管理端 /admin/data-exchange/（数据集清单）
   → 专业工具 /r4/import/：下载模板 → 上传 → 预检（零写入）→ 提交（重新校验）
   → DataImportJob / DataImportRowError / StudentRecord
```

---

## 15. 统计口径与排除项

| 指标 | 口径 | 值 |
|---|---|---|
| Django App 总数 | `apps.get_app_configs()` | 26（项目 20 + 内置 6） |
| 有效模型 | 排除 `auto_created=True` 的 M2M 中间表 | 120（项目 114 + 内置 6） |
| 数据库表 | 模型 `db_table` 去重 | 126（含 6 个自动中间表） |
| URL 路由 | URLResolver 递归展开，含 include | 305 |
| 视图函数 | `views.py`/`ui_views.py`/`views/` 中 def（含辅助） | 544（公开 426） |
| 被路由引用的视图回调 | URL 解析后的 distinct callback | 283 |
| 业务服务函数 | `services.py`/`services/` 中非下划线 def | 483 |
| 模板 | `templates/` + `smass_workspace/templates/` 的 `.html` | 202（产品 54） |
| 测试用例 | `test_*.py` 中 `def test_` | 1800 |
| 迁移文件 | 各 app `migrations/*.py`（不含 `__init__`） | 36 |
| 角色编码 | `r21_account.models.RoleCode` | 4 |
| 人员类型 | `PersonType` | 3 |
| 授权动作 | `authorization.ACTION_PERMISSIONS` | 9 |
| 授权资源 | `authorization.RESOURCES` | 3 |
| 产品导航项 | 三端 `navigation` 菜单项（含辅导员条件项） | 42 |

**排除项**：`.git`、`.local`、`staticfiles`、`__pycache__`、`node_modules`、
`media`、`private_uploads`、`logs`、`migrations`（仅计数，不解析）。

**未统计/未知**：
- 前端 JS 行数与组件数（无构建系统，未纳入统计）；
- 历史模块中未被产品 URL 引用的视图（`unreferenced_view_functions` 144 个，
  多为独立 settings 下的页面/操作，产品配置未挂载）；
- 正式库之外的其它历史库（`smass_r*`/`smass_s*`）的表结构未逐一审计。

---

## 16. 架构层面的已知结论

1. **产品层是"薄壳 + 聚合"**：`smass_workspace` 无模型，只做导航、守卫、
   只读聚合与三端页面；写操作全部下沉到既有服务。
2. **两套前端体系并存**：产品自建设计系统（三端）与历史 Bootstrap 页面
   （专业工具入口）。这是当前的过渡形态，不是"三套产品"。
3. **安全模块未接入产品路径**：MFA/step-up/双人审批/策略引擎/隐私最小化
   有独立实现与测试，但 `settings_product` 未注册、`urls_product` 未 include，
   因此三端不提供这些保护。详见 `08_Gaps_and_Technical_Debt.md`。
4. **无异步任务与外部服务**：所有业务同步执行，缓存为进程内，适合单机部署；
   多实例部署需替换缓存与会话后端（当前未做）。
