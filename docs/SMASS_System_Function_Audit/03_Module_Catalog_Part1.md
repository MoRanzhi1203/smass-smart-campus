# 03 模块功能目录 · Part 1

> 覆盖模块 1–8：工作台/身份/组织/学籍/教师/教务/选课/排课。
> 功能状态与证据一一对应；证据文件以仓库相对路径给出。

---

## 模块 1：工作台与个人中心

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 三端工作台与个人中心 |
| 业务目标 | 按角色提供统一入口、聚合待办与关键指标、共用通知与账号信息 |
| 面向账号 | 学生、教师、辅导员、学院管理员、系统管理员（无角色账号仅个人中心/通知） |
| 业务领域 | 平台入口 |
| 代码位置 | `smass_workspace/views/{auth,common,student,teacher,admin}.py`、`templates/workspace/` |
| 原始来源 | 新建（产品融合层），非 R 系列模块 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M1-F01 | 统一登录 | 全部 | `/login/` · `auth.login_view` | Account/LoginAttempt | 限速、账号停用 | 写 LoginAttempt | `test_login_lands_*` | IMPLEMENTED_AND_VERIFIED |
| M1-F02 | 按角色落地 | 全部 | `auth.root_view`/登录后 | AccountRole | 角色优先级 | 无 | 产品层 40 例 + E2E | IMPLEMENTED_AND_VERIFIED |
| M1-F03 | 无角色提示 | 无角色 | `/no-role/` · `common.no_role` | Account | 无角色 | 无 | `test_login_lands_no_role` | IMPLEMENTED_AND_VERIFIED |
| M1-F04 | 学生工作台聚合 | 学生 | `/student/` · `student.home` | StudentRecord/Enrollment/Attendance/Bill/Activity | 学籍存在 | 只读 | E2E 截图 01 | IMPLEMENTED_AND_VERIFIED |
| M1-F05 | 教师工作台聚合 | 教师 | `/teacher/` · `teacher.home` | TeachingAssignment/LeaveRequest/ApprovalTask | 教学班 | 只读 | E2E 截图 05 | IMPLEMENTED_AND_VERIFIED |
| M1-F06 | 管理总览 | 管理员 | `/admin/` · `admin.home` | 多模型计数 + RequestMetric | 范围 | 只读 | E2E 截图 11 | IMPLEMENTED_AND_VERIFIED |
| M1-F07 | 个人中心 | 全部 | `/profile/` · `common.profile` | Account/StudentRecord/OrganizationMembership | 登录 | 只读 | `test_profile_and_notifications_for_all_roles` | IMPLEMENTED_AND_VERIFIED |
| M1-F08 | 通知中心 | 全部 | `/notifications/` · `common.notifications` | Notification/Announcement | 登录 | 打开即标记已读 | 同上 | IMPLEMENTED_AND_VERIFIED |
| M1-F09 | 多端切换 | 多角色 | `base.html` 切换器 | AccountRole | 多端 | 无 | E2E（教师+辅导员） | IMPLEMENTED_AND_VERIFIED |
| M1-F10 | 退出登录 | 全部 | `POST /logout/` | Session | 仅 POST | 销毁会话 | `test_logout_requires_post` | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | URL | 主要区域 | 操作 | 空状态 | 错误提示 |
|---|---|---|---|---|---|
| 登录页 | `/login/` | 品牌区 + 表单（登录名/密码/CSRF） | 登录 | — | 账号或密码错误 / 锁定剩余秒数 |
| 学生工作台 | `/student/` | Hero 指标、4 统计卡、今日课表、待办、活动、公告 | 跳转 | 各区块独立空状态 | 无学籍时顶部警告 |
| 教师工作台 | `/teacher/` | 指标、今日课程、教学班、待办、辅导员摘要、公告 | 跳转/审批入口 | 独立空状态 | — |
| 管理总览 | `/admin/` | 8 统计卡、近 24h 请求、健康、告警 | 跳转 | 无指标时空状态 | — |
| 个人中心 | `/profile/` | 账号、学籍、组织关系、安全、可用工作台 | 改密链接 | 「暂无组织关系」 | — |
| 通知中心 | `/notifications/` | 通知 + 公告合并列表 | 查看 | 「暂无通知」 | — |

### D. 后端业务规则

- `login_view`：`login_lock_status` 前置检查；`authenticate`；成功 `register_login_result`；
  `safe_next` 只接受站内地址。
- 落地：`permissions.landing_kind` → `landing_url`；无角色 → `no_role`（403）。
- 聚合服务只读，不写库；通知中心打开时 `Notification.objects.filter(recipient, is_read=False).update(is_read=True)`。
- 退出仅接受 POST（`require_POST`），GET 返回 405。

### E. 验证状态

全部 `IMPLEMENTED_AND_VERIFIED`：产品层 40 例 + Chromium 27 项 + 冒烟 71 页。

---

## 模块 2：统一账号、身份与角色权限

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 统一身份与授权 |
| 业务目标 | 一套账号承载学生/教师/管理员身份，角色与组织范围决定可见与可做 |
| 面向账号 | 全部 |
| 代码位置 | `r21_account/`（models/services/permissions/authorization/backends/middleware）、`smass_workspace/permissions.py` |
| 原始来源 | R21/R22 + 产品层守卫 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M2-F01 | 创建账号 | 系统管理员 | `/admin/users/` · `admin.user_create` | Account | 登录名唯一、必填 | 新增 Account + must_change_password | `test_create_course_from_console`（同路径） | IMPLEMENTED_AND_VERIFIED |
| M2-F02 | 授予角色 | 系统管理员 | `admin.user_role` | AccountRole | 角色编码合法 | 新增角色 + 同步 Group | `test_grant_role_changes_landing` | IMPLEMENTED_AND_VERIFIED |
| M2-F03 | 撤销角色 | 系统管理员 | `admin.user_role` | AccountRole | 角色存在 | revoked_at 写入 | 同上（撤销分支） | IMPLEMENTED_AND_VERIFIED |
| M2-F04 | 停用/启用 | 系统管理员 | `admin.user_toggle` | Account | 不能停用自己 | is_active 切换 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M2-F05 | 重置一次性口令 | 系统管理员 | `admin.user_reset` | Account/AccountSecurityState | 随机口令、TTL | 口令哈希 + 强制改密 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M2-F06 | 改密 | 本人 | `/account/password/`（r21 视图） | Account | 密码策略 | 哈希更新、会话世代 | r21 套件 110 例 | IMPLEMENTED_AND_VERIFIED |
| M2-F07 | 登录限速 | 全部 | `login_lock_status` | LoginAttempt | 次数/窗口 | 记录尝试 | `test_auth_integration` | IMPLEMENTED_AND_VERIFIED |
| M2-F08 | 会话失效 | 全部 | `PasswordLifecycleMiddleware` | AccountSecurityState | session_epoch | 递增 epoch | r21/S02 测试 | IMPLEMENTED_AND_VERIFIED |
| M2-F09 | 角色权限矩阵 | 全部 | `r21_account/permissions.py` | Permission/Group | 9 动作 | 同步 Group | r21 测试 | IMPLEMENTED_AND_VERIFIED |
| M2-F10 | 账号审计 | 管理员 | `/admin/audit/` | AccountAuditLog/LoginAttempt | 只读 | 写日志 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M2-F11 | 历史账号映射 | 迁移脚本 | `scripts/legacy_migration.py` | LegacyAccountLink | 幂等、PII 掩码 | 新增 link | `migration/verify.json` | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | URL | 区域 | 操作 | 权限 |
|---|---|---|---|---|
| 用户账号 | `/admin/users/` | 筛选、账号表、创建表单 | 创建、授/撤角色、停用、重置 | 超管写；学院管理员只读 |
| 角色与权限 | `/admin/roles/` | 4 角色卡 + 当前角色 | 查看 | 管理员 |
| 安全审计 | `/admin/audit/` | 操作日志、登录尝试 | 查看 | 管理员 |
| 个人中心 | `/profile/` | 账号/角色/组织/改密入口 | 查看 | 登录 |

### D. 后端业务规则

- `grant_role`：写 `AccountRole` + `sync_account_groups`（Django Group）；
  同一角色重复授予幂等；撤销写 `revoked_at/revoked_by`。
- `set_temporary_password`：随机口令、`must_change_password=True`、TTL 由
  `PASSWORD_LIFECYCLE.TEMP_PASSWORD_TTL_MINUTES` 控制。
- 授权判定：`has_action` 未知动作拒绝；`require_object` 三检（存在+动作+可见集合）。
- 拒绝条件：非系统管理员调用用户写接口 → 403（`require_system_admin`）。

### E. 验证状态

`IMPLEMENTED_AND_VERIFIED`。安全增强（MFA/step-up）未接入产品，见 02 §11。

---

## 模块 3：组织、学院、专业、年级与班级

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 组织架构 |
| 业务目标 | 以单亲树承载学院/专业/年级/班级/部门，作为数据范围与归属依据 |
| 面向账号 | 系统管理员（写）、学院管理员（本院读）、全体（个人归属） |
| 代码位置 | `smass_organization/models.py::OrganizationUnit`、`services.py`、`ui_views.py` |
| 原始来源 | R4（`app01.College/Major/Classes/Grade/Department` 迁移） |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M3-F01 | 组织树查询 | 管理员 | `/admin/organizations/` · `admin.organizations` | OrganizationUnit | 范围过滤 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M3-F02 | 创建组织单元 | 系统管理员 | `/r4/units/new/` · `r4_ui.unit_new` | OrganizationUnit | 父子类型白名单、防环 | 新增 | R4 69 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M3-F03 | 移动组织单元 | 系统管理员 | `/r4/units/<pk>/edit/` | OrganizationUnit | `validate_parent` 防环 | parent 变更 | R4 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M3-F04 | 成员关系 | 管理员 | `/admin/organizations/` | OrganizationMembership | 唯一有效关系 | 新增/结束 | 迁移 + 测试 | IMPLEMENTED_AND_VERIFIED |
| M3-F05 | 字段策略 | 系统管理员 | `/admin/settings/` | StudentFieldDefinition | 允许列表 | 配置 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 备注 |
|---|---|---|---|
| `/admin/organizations/` | 组织表（编码/名称/类型/上级/成员数/状态）+ 人员归属列表 | 查看 | 产品内无新增/编辑入口 |
| `/r4/units/` | 组织树 + 新建/编辑 | 新增、编辑 | 历史 Bootstrap 页 |

### D. 后端业务规则

- `ALLOWED_CHILDREN`：根仅学院/部门；学院可挂专业/年级/部门；专业/年级仅班级；部门可自嵌套。
- `validate_parent`：禁止把节点移动到自己的子树（防环）。
- 删除：`on_delete=PROTECT`（有子节点/引用时拒绝）。
- 范围：学院管理员按 `scope_college` 收集子树；空 scope → 空集。

### E. 验证状态

产品只读页 `IMPLEMENTED_AND_VERIFIED`；写入依赖 R4 专业工具页
（`IMPLEMENTED_AND_VERIFIED`，R4 回归 69 例）。

---

## 模块 4：学生档案与学籍

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 学籍档案 |
| 业务目标 | 维护学生学籍、组织归属、变更历史，支撑课表/考勤/费用/活动 |
| 面向账号 | 学生（本人）、教师/辅导员（范围内）、学院管理员/系统管理员（管理） |
| 代码位置 | `smass_organization`（StudentRecord/Change/FieldDefinition）、`smass_enrollment`（异动） |
| 原始来源 | R4 + R12；app01.Student 迁移 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M4-F01 | 查看本人学籍 | 学生 | `/student/record/` | StudentRecord | 本人 | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M4-F02 | 学籍列表与筛选 | 管理员 | `/admin/records/` · `admin.records` | StudentRecord | 范围 | 只读 | `test_college_admin_scope_excludes_other_college` | IMPLEMENTED_AND_VERIFIED |
| M4-F03 | 学籍详情 | 管理员 | `/admin/records/<no>/` | StudentRecord/Enrollment | 对象级 | 只读 | `test_system_admin_can_view_any_record` | IMPLEMENTED_AND_VERIFIED |
| M4-F04 | 编辑学籍 | 系统管理员 | `admin.record_update` | StudentRecord/Change | 乐观锁、字段策略 | 写变更历史 | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M4-F05 | 学籍变更历史 | 学生/管理员 | 记录页 | StudentRecordChange | 只读 | 追加 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M4-F06 | 转专业申请 | 学生（服务）/学院管理员（审批） | `/admin/record-changes/` | MajorTransferRequest | 状态机 | submitted→approved/rejected | 迁移种子 + 产品冒烟 | IMPLEMENTED_NOT_VERIFIED（无产品提交入口） |
| M4-F07 | 学籍状态变更 | 同上 | `/admin/record-changes/` | StudentStatusChange | 状态机 | submitted→approved | 同上 | IMPLEMENTED_NOT_VERIFIED（无产品提交入口） |
| M4-F08 | 自动分班 | 教务/管理员 | `/r12/placement/` | PlacementRule/Batch/Assignment | 规则/容量 | 预览→执行→回滚 | R12 43 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M4-F09 | 学籍导入 | 管理员 | `/r4/import/` | DataImportJob/StudentRecord | 预检→提交 | 批次/行错误 | S25 85 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M4-F10 | 住宿摘要 | 学生/管理员 | `/student/dormitory/`、学籍详情 | StudentRecord.extra | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 | 权限 |
|---|---|---|---|---|
| `/admin/records/` | 筛选（学号/姓名/状态）+ 表格 | 查看 | 无匹配提示 + 导入入口 | 范围 |
| `/admin/records/<no>/` | 基本信息、选课、编辑表单 | 超管编辑 | 无选课提示 | 对象级 |
| `/student/record/` | 信息、变更时间线、住宿、账号 | 查看 | 未绑定学籍警告 | 本人 |
| `/admin/record-changes/` | 转专业表、状态变更表 | 批准/驳回 | 空提示 | 范围 |

### D. 后端业务规则

- `update_student`：乐观锁 `expected_version`；写 `StudentRecordChange`；
  字段可编辑性由 `StudentFieldDefinition.editable_roles` 控制。
- 转专业：`submit_transfer` → `approve_transfer`（校验目标专业/班级）→
  `apply_transfer`（真正改 unit）分两步；**产品端只提供审批，不提供提交与执行**。
- 状态变更：`submit/approve/reject/apply` 四步，产品端仅审批。
- 拒绝：非范围内学生 → 403；非法状态 → `EnrollmentError`。

### E. 验证状态

查看/编辑/历史 `IMPLEMENTED_AND_VERIFIED`；
异动的提交与执行入口 `PARTIALLY_IMPLEMENTED`（服务与深层页存在，产品未接入）。

---

## 模块 5：教师档案与教学管理

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 教师档案与任课管理 |
| 业务目标 | 维护教师基本信息与任课关系，支撑教师工作台、课表与审批范围 |
| 面向账号 | 教师（本人）、辅导员（扩展）、管理员（查看） |
| 代码位置 | `r21_account.TeacherProfile`、`smass_academic.TeachingAssignment`、`app01.Teacher`（历史） |
| 原始来源 | R21 档案 + R5 任课；app01.Teacher 迁移 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M5-F01 | 教师档案 | 教师/管理员 | `/profile/`、教师工作台 | TeacherProfile | 账号 1:1 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M5-F02 | 任课分配 | 系统管理员 | `/r5/sections/<pk>/assign/` | TeachingAssignment | 账号有效、未撤销 | 新增/撤销 | R5 56 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M5-F03 | 我的教学班 | 教师 | `/teacher/courses/` | TeachingAssignment/TeachingSection | 本人 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M5-F04 | 教学班名单 | 教师 | `/teacher/sections/` | TeachingSection/Enrollment | 本人教学班 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M5-F05 | 教师课表 | 教师 | `/teacher/timetable/` | ScheduleEntry.teacher | 本人 | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M5-F06 | 教师档案维护（新增/编辑） | 系统管理员 | **无产品入口**；app01 旧后台有教师 CRUD | app01.Teacher / TeacherProfile | — | — | `templates/admin/teacher.html` | PARTIALLY_IMPLEMENTED（R21 无教师 CRUD；仅迁移与 app01 旧页） |

### C. 页面说明

| 页面 | 区域 | 操作 | 备注 |
|---|---|---|---|
| `/teacher/` | 教学班、学生数、今日课程 | 查看 | 教师档案仅展示姓名/工号（来自 TeacherProfile） |
| `/teacher/courses/` | 授课表（课程/教学班/学期/学分/人数） | 查看 | 无编辑 |
| `/teacher/sections/` | 教学班卡 + 学生名单 | 查看 | 无编辑 |
| `/r5/sections/<pk>/assign/` | 分配/撤销任课 | 分配、撤销 | Bootstrap 页 |

### D. 后端业务规则

- `TeachingAssignment`：`account` FK + `revoked_at`；`my_sections` 只取未撤销。
- 教师范围：`section_students` 由任课关系推导，不读组织班级。
- **缺口**：产品与 R21 都没有"教师档案 CRUD"服务；教师档案只能由迁移脚本
  或 app01 旧后台维护。教师新增/调岗无产品化流程。

### E. 验证状态

查看类 `IMPLEMENTED_AND_VERIFIED`；档案维护 `PARTIALLY_IMPLEMENTED`（缺 CRUD）。

---

## 模块 6：学年、学期、课程与教学班

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 教务基础数据 |
| 业务目标 | 建立学年/学期/课程/教学班，作为选课、排课、考勤的前置 |
| 面向账号 | 系统管理员（写）、学院管理员（读）、教师/学生（读） |
| 代码位置 | `smass_academic/models.py`、`services.py`、`ui_views.py`；产品 `admin.academics` |
| 原始来源 | R5 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M6-F01 | 学年列表/新建 | 系统管理员 | `/admin/academics/` · `admin.year_create` | AcademicYear | 编码唯一、日期区间 | 新增 | 产品层测试 | IMPLEMENTED_AND_VERIFIED |
| M6-F02 | 学期列表/新建 | 系统管理员 | `admin.term_create` | AcademicTerm | 落在学年区间 | 新增 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M6-F03 | 课程列表/新建 | 系统管理员 | `admin.course_create` | Course | 编码唯一、学分≥0 | 新增 | `test_create_course_from_console` | IMPLEMENTED_AND_VERIFIED |
| M6-F04 | 教学班列表/新建 | 系统管理员 | `/admin/sections/` · `admin.section_create` | TeachingSection | 学期/课程有效、容量≥0 | 新增 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M6-F05 | 教学班名单 | 管理员 | `/admin/sections/<pk>/roster/` | Enrollment/TeachingAssignment | 只读 | 只读 | 冒烟动态页 | IMPLEMENTED_AND_VERIFIED |
| M6-F06 | 学年/学期/课程深层管理 | 系统管理员 | `/r5/years/`、`/r5/terms/`、`/r5/courses/` | 同上 | 同服务 | 新增/编辑 | R5 56 例 | IMPLEMENTED_AND_VERIFIED（专业工具） |

### C. 页面说明

| 页面 | 区域 | 表单字段 | 操作 | 空状态 |
|---|---|---|---|---|
| `/admin/academics/` | 学年表、学期表、课程表 + 三个新建表单（超管） | 编码/起止/是否当前；学年/学期/起止；编码/名称/学分/类型 | 创建 | 「暂无学年」等 |
| `/admin/sections/` | 教学班表 + 新建表单 | 学期/课程/班号/容量 | 创建、名单 | 「暂无教学班」 |
| `/admin/sections/<pk>/roster/` | 名单 + 任课教师 | — | 查看 | 无学生提示 |

### D. 后端业务规则

- `create_year/term/course/section`：编码唯一、日期区间校验、容量非负；
  学期必须落在学年区间。
- 教学班创建不自动分配教师或学生（需 R5 深层页操作）。
- 拒绝：非系统管理员 → 403；重复编码 → `DuplicateError` 提示。

### E. 验证状态

`IMPLEMENTED_AND_VERIFIED`（产品创建 + R5 深层管理）。

---

## 模块 7：选课与学生名单

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 选课 |
| 业务目标 | 建立学生与教学班的选课关系，驱动课表、考勤与成绩基础 |
| 面向账号 | 学生（查看本人）、教师（看名单）、管理员（管理） |
| 代码位置 | `smass_academic.models.Enrollment/EnrollmentHistory`、`ui_views.enroll_page` 等 |
| 原始来源 | R5 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M7-F01 | 学生选课 | 学生（历史页） | `/r5/enroll/` · `r5_ui.enroll_page` | Enrollment | 容量/状态 | enrolled | R5 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M7-F02 | 退课 | 学生/管理员 | `/r5/enrollments/<pk>/drop/` | Enrollment | 状态机 | dropped | R5 测试 | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M7-F03 | 选课名单 | 教师/管理员 | `/teacher/sections/`、`/admin/sections/<pk>/roster/` | Enrollment | 范围 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M7-F04 | 我的课程 | 学生 | `/student/courses/` | Enrollment/TeachingSection | 本人 | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M7-F05 | 选课历史 | 管理员 | 无产品页 | EnrollmentHistory | — | 追加 | R5 测试 | IMPLEMENTED_NOT_VERIFIED（无产品入口） |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/student/courses/` | 课程/教学班/教师/学期/学分/状态 | 查看 | 「暂无选课记录」 |
| `/admin/sections/<pk>/roster/` | 名单 + 任课教师 | 查看 | 「暂无学生选课」 |
| `/r5/enroll/` | 可选教学班 + 我的选课 | 选课/退课 | — |

### D. 后端业务规则

- 容量：`TeachingSection.capacity=0` 表示不限；满员拒绝。
- 唯一性：同一学生同一教学班唯一（DB 约束 + 服务校验）。
- 退课写 `EnrollmentHistory`；`status='dropped'` 不参与课表/名单。
- **缺口**：产品端没有选课/退课入口，学生必须走 `/r5/enroll/` 历史页
  （导航未暴露）。

### E. 验证状态

查看 `IMPLEMENTED_AND_VERIFIED`；选课/退课 `IMPLEMENTED_AND_VERIFIED`（专业工具，
产品导航不可达）。产品化程度记为 `PARTIALLY_IMPLEMENTED`。

---

## 模块 8：智能排课与三张课表

### A. 模块概述

| 项 | 内容 |
|---|---|
| 名称 | 排课与课表 |
| 业务目标 | 在硬约束下生成周课表并发布，供学生/教师/教室三视角查看 |
| 面向账号 | 系统管理员/教务（求解发布）、教师/学生（查看） |
| 代码位置 | `smass_scheduling/`（models/solver/views）、`smass/urls_r11.py` |
| 原始来源 | R11 |

### B. 功能清单

| ID | 功能 | 角色 | 页面/视图 | 模型 | 校验 | 状态变化 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| M8-F01 | 节次配置 | 管理员 | `/r11/plan/`（数据） | TimeSlot | 周一–周日、节次≥1 | 新增 | R11 40 例 | IMPLEMENTED_AND_VERIFIED |
| M8-F02 | 教师约束/可用时段 | 教师/管理员 | `/r11/plan/` | TeacherAvailability/TeacherConstraint | 唯一约束 | 新增 | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F03 | 群体（Cohort） | 管理员 | 数据层 | Cohort | 编码唯一 | 新增 | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F04 | 课时需求 | 管理员 | `/r11/plan/` | LessonRequirement | 周次数/节数 | 新增 | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F05 | 求解 | 管理员 | `/r11/plan/<id>/solve/` | ScheduleRun/Entry/Conflict | 硬约束 | draft→solved | 求解器测试 + `verify_run` | IMPLEMENTED_AND_VERIFIED（专业工具） |
| M8-F06 | 发布 | 管理员 | `/r11/plan/<id>/publish/` | ScheduleRun.status | 冲突=0 | published | R11 测试 + 产品页读取 | IMPLEMENTED_AND_VERIFIED |
| M8-F07 | 冲突解释 | 管理员 | `/r11/plan/<id>/conflicts/` | ScheduleConflict | 只读 | — | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F08 | 学生课表 | 学生 | `/student/timetable/` | ScheduleEntry/Enrollment | 已发布 run | 只读 | E2E | IMPLEMENTED_AND_VERIFIED |
| M8-F09 | 教师课表 | 教师 | `/teacher/timetable/` | ScheduleEntry.teacher | 已发布 run | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |
| M8-F10 | 教室课表 | 管理员 | `/r11/timetable/room/<id>/` | ScheduleEntry.room | 管理员 | 只读 | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F11 | 课表 JSON | 登录用户 | `/r11/timetable/mine.json` | ScheduleEntry | 本人 | 只读 | R11 测试 | IMPLEMENTED_AND_VERIFIED |
| M8-F12 | 排课运行列表 | 管理员 | `/admin/scheduling/` | ScheduleRun | 只读 | 只读 | 产品冒烟 | IMPLEMENTED_AND_VERIFIED |

### C. 页面说明

| 页面 | 区域 | 操作 | 空状态 |
|---|---|---|---|
| `/admin/scheduling/` | 4 统计卡 + 运行表（学期/状态/已排/冲突/条目/算法/发布） | 查看；进专业工具 | 「还没有排课运行」 |
| `/student/timetable/` | 周课表（节次×周一–周日） | 查看 | 「暂无课表」+ 已发布提示 |
| `/teacher/timetable/` | 周课表 | 查看 | 同上 |
| `/r11/plan/` | 运行/需求/求解/发布/冲突 | 求解、发布 | Bootstrap 页 |

### D. 后端业务规则

- 求解器 `deterministic-constructive-v1`：同输入同输出；硬冲突 0 或明确不可行；
  软成本可读；`verify_run` 独立复核。
- 硬约束下沉：`ScheduleEntry` 四个唯一约束（教室/教师/群体/需求）。
- 发布前置：`status` 迁移校验；发布后学生/教师端即时可见。
- 拒绝：非管理员调用求解/发布 → 403；未发布 run 不出现在产品课表。

### E. 验证状态

课表读取 `IMPLEMENTED_AND_VERIFIED`（产品三端）；
求解/发布 `IMPLEMENTED_AND_VERIFIED`（R11 40 例 + 独立复核，经专业工具页）。

