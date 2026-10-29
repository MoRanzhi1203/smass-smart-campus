# SMASS R10 UI 清单（U0 基线审计）

> 生成方式：`scripts/r10_ui_inventory.py` 自动枚举 Django resolver（不靠推断）。
> 基线 SHA：`5b69d58`　分支：`feat/smass-r4-r10-integrated-platform`
> 设置：`smass.settings_r10`　库：`smass_r10_release`（隔离，合成数据）
> 枚举结果：**60 路由**（54 页面 + 6 API）

## 1. 汇总

| 指标 | 数量 |
|---|---|
| 路由总数 | 60 |
| 页面路由 | 54 |
| API 路由 | 6 |
| 有模板的页面 | 14 |
| **只有 JSON/无页面** | **22** |
| 登录/登出等身份路由 | 21（7 组重复挂载） |

### 关键结论（U0 发现的真实缺口）

| 缺口 | 说明 |
|---|---|
| R4 学生详情页 | 路由 `/r4/students/<student_no>/` 存在，**模板缺失** |
| R4 数据导入 | `/r4/import/preview/`、`/r4/import/commit/` 仅 API，**无页面** |
| R5 新建表单 | year/term/course/section 的 create 仅 API，**列表页无新建入口** |
| R6 新建定义/实例 | 仅 API，**无表单** |
| R7 报表 | `/r7/reports/<code>/run|export/` 仅 API，**无报表页面** |
| R8 开发者页 | 仅 `openapi.json`，**无页面** |
| R9 运维页 | health/ready/metrics/alerts 仅 JSON，**无页面** |

## 2. 身份与导航路由

| 路由 | 视图 | 说明 |
|---|---|---|
| `/r10/` | `nav_home` | 统一入口（公开，未登录可访问） |
| `/r21/login/` | `r21.login_view` | 统一登录（RoutePolicy 拒绝时也跳此） |
| `/r21/logout/` | `r21.logout_view` | 登出 |
| `/r21/home/` | RedirectView → `/r10/` | 登录后落点 |
| `/r21/change-password/` | RedirectView → `/r10/` | 强制改密落点（**简化，待补真实改密页**） |
| `/r4/login/` `/r4/logout/` | r21 views | 模块级重复挂载 |
| `/r5/login/` `/r5/logout/` | r21 views | 同上 |
| `/r6/login/` `/r6/logout/` | r21 views | 同上 |
| `/r7/login/` `/r7/logout/` | r21 views | 同上 |
| `/r8/login/` | r21 views | 同上 |

## 3. R4 组织与档案

| 路由 | 方法与角色 | 模板 | 数据源 | 表单 | 空态 | 错误 | 响应式 | E2E |
|---|---|---|---|---|---|---|---|---|
| `/r4/units/` | GET·admin/college/teacher | `r4/unit_list.html` | `OrganizationUnit` | 无（只读列表） | 有 | 403 纯文本 | 是（继承 base） | 有（`test_r4_browser`） |
| `/r4/units/tree/` | GET·同上 | — | 同上 | — | — | JSON | — | 无 |
| `/r4/units/create/` | POST·system_admin | — | 同上 | **仅 API** | — | JSON 400 | — | 单测 |
| `/r4/units/<pk>/move/` | POST·system_admin | — | 同上 | **仅 API** | — | 环/类型错误 JSON | — | 单测 |
| `/r4/students/` | GET·admin/college/teacher | `r4/student_list.html` | `StudentRecord`（scope） | 无（只读列表） | 有 | 403 纯文本 | 是 | 有 |
| `/r4/students/export/` | GET·同上 | — | 同上 | — | — | CSV | 否（下载） | 单测 |
| `/r4/students/<student_no>/` | GET·同上 | **缺失** | 同上 | **无页面** | — | JSON | — | 无 |
| `/r4/import/preview/` | POST·admin | — | `DataImportJob` | **无页面** | — | JSON | — | 单测 |
| `/r4/import/commit/` | POST·admin | — | 同上 | **无页面** | — | JSON | — | 单测 |
| `/r4/health/` | GET·公开 | — | — | — | — | JSON | — | 无 |

## 4. R5 教学

| 路由 | 方法与角色 | 模板 | 表单 | E2E |
|---|---|---|---|---|
| `/r5/years/` | GET·admin/college | `r5/year_list.html` | **无新建表单** | 有（渲染断言） |
| `/r5/years/create/` | POST·system_admin | — | 仅 API | 单测 |
| `/r5/years/<pk>/activate/` | POST·system_admin | — | 仅 API | 单测 |
| `/r5/terms/` | GET·admin/college | `r5/term_list.html` | **无新建表单** | 有 |
| `/r5/terms/create/` | POST·system_admin | — | 仅 API | 单测 |
| `/r5/courses/` | GET·admin/college | `r5/course_list.html` | **无新建表单** | 有 |
| `/r5/courses/create/` | POST·system_admin | — | 仅 API | 单测 |
| `/r5/sections/` | GET·admin/college | `r5/section_list.html` | **无新建表单** | 有 |
| `/r5/sections/create/` | POST·system_admin | — | 仅 API | 单测 |
| `/r5/workspace/` | GET·teacher | `r5/teacher_workspace.html` | — | 有 |
| `/r5/sections/<pk>/roster/` | GET·teacher | — | — | 单测 |
| `/r5/my-courses/` | GET·student | `r5/my_sections.html` | — | 有 |

## 5. R6 审批

| 路由 | 方法与角色 | 模板 | 表单 | E2E |
|---|---|---|---|---|
| `/r6/definitions/` | GET·admin | `r6/definition_list.html` | **无新建表单** | 有 |
| `/r6/definitions/create/` | POST·admin | — | 仅 API | 单测 |
| `/r6/instances/` | GET·staff | `r6/instance_list.html` | **无提交表单** | 有 |
| `/r6/instances/create/` | POST·staff | — | 仅 API | 单测 |
| `/r6/instances/<pk>/action/` | POST·staff | — | 仅 API（页面用 fetch） | 有（浏览器 submit/approve） |
| `/r6/tasks/` | GET·staff | `r6/task_list.html` | — | 有 |
| `/r6/notifications/` | GET·staff | `r6/notification_list.html` | — | 有 |

## 6. R7 分析

| 路由 | 方法与角色 | 模板 | 表单 | E2E |
|---|---|---|---|---|
| `/r7/dashboard/` | GET·staff | `r7/dashboard.html` | **无筛选** | 有（浏览器） |
| `/r7/metrics/` | GET·staff | `r7/metric_list.html` | — | 有 |
| `/r7/reports/<code>/run/` | GET·staff | **缺失** | **无页面** | 单测 |
| `/r7/reports/<code>/export/` | GET·staff | — | — | 单测 |

## 7. R8 / R9

| 路由 | 类型 | 页面 | 说明 |
|---|---|---|---|
| `/api/v1/openapi.json` | API | **无页面** | 仅原始 JSON |
| `/api/v1/units|students|sections|workflow/instances|sync/` | API | — | 5 个端点 |
| `/r9/health/` | JSON | **无页面** | 仅 `{"ok":true}` |
| `/r9/ready/` | JSON | **无页面** | 探针结果 |
| `/r9/metrics/` | JSON | **无页面** | P50/P95/P99 |
| `/r9/alerts/` | JSON | **无页面** | 告警评估 |

## 8. U0 判定

| 维度 | 状态 |
|---|---|
| 路由可达 | 60/60 已注册 |
| 有页面 | 14 个业务页 + 1 个导航页 |
| **有可用表单** | **0 个**（全部新建/编辑靠 API） |
| 有侧边栏 | 无（仅顶部条） |
| 有设计系统 | 无（单文件内联 CSS） |
| 有弹窗/确认 | 无 |
| 有加载/空态组件 | 仅有 `{% empty %}` 文本 |
| 有统一 403/404/500 页 | 无（403 返回纯文本"无权限"） |
| 三浏览器 E2E | 仅 Chromium 部分页面 |

**结论**：当前是"只读列表 + 导航条"，距"可用的管理产品"差距集中在
表单、交互反馈、权限提示、响应式抽屉、报表页与运维页。
