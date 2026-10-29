# SMASS R10 UI/UX 架构（U1/U2）

## 1. 技术选型（基于仓库现状，不引入前端框架）

| 层 | 选型 | 依据 |
|---|---|---|
| 渲染 | Django 模板 | 既有 14 个模板 + 服务层，无需迁移 |
| CSS 基础 | **本地** Bootstrap 5.3.2 | `static/plugins/bootstrap-5.3.2/` 已存在，**不用 CDN** |
| 设计层 | `static/css/r10.css` | 令牌 + 外壳 + 组件，覆盖在 Bootstrap 之上 |
| 交互 | `static/js/r10.js`（原生 JS） | 无框架、无构建步骤 |
| 图表 | 本地 `static/js/echarts.js` | 已存在（U6 使用） |
| 图标 | Unicode 几何符号 | 避免新增图标库依赖 |

## 2. 页面组合关系

```
templates/r10/base.html          ← 唯一外壳（侧边栏 + 顶栏 + 抽屉 + 消息 + toast）
├── templates/r10/home.html      ← /r10/ 概览
├── templates/r4/*.html          ← 4 页（unit/student/import + …）
├── templates/r5/*.html          ← 6 页
├── templates/r6/*.html          ← 4 页
├── templates/r7/*.html          ← 2 页
├── templates/r8/docs.html       ← API 文档
└── templates/r9/status.html     ← 运维状态
```

所有业务模板只有 `{% block title %}` / `{% block breadcrumb %}` / `{% block content %}` /
`{% block scripts %}`，**不重复定义 head、导航或页脚**。

## 3. 外壳结构

```html
<div class="sm-shell">
  <aside id="sm-sidebar" class="sm-sidebar">…分组导航…</aside>
  <div id="sm-backdrop" class="sm-backdrop"></div>
  <div class="sm-main">
    <header class="sm-topbar">
      <button id="sm-drawer-toggle" aria-controls="sm-sidebar" aria-expanded="false">
      <nav class="sm-breadcrumb">首页 / …</nav>
      <div class="sm-user">…身份 + 退出…</div>
    </header>
    <main id="sm-content" class="sm-content">{% block content %}</main>
  </div>
</div>
```

## 4. 导航分组与路由映射

| 分组 | 条目 | 路由 | 高亮判定 |
|---|---|---|---|
| 组织与档案 | 组织单元 | `/r4/units/` | `path[:3] == '/r4'` |
| | 学生档案 | `/r4/students/` | `'/r4/students' in path` |
| | 数据导入 | `/r4/import/` | `'/r4/import' in path` |
| 教学管理 | 学年学期 | `/r5/years/` | `'/r5/years' or '/r5/terms'` |
| | 课程目录 | `/r5/courses/` | `'/r5/courses'` |
| | 教学班 | `/r5/sections/` | `'/r5/sections'` |
| | 教师工作台 | `/r5/workspace/` | `'/r5/workspace'` |
| | 我的课程 | `/r5/my-courses/` | `'/r5/my-courses'` |
| 审批流程 | 流程定义 | `/r6/definitions/` | `'/r6/definitions'` |
| | 流程实例 | `/r6/instances/` | `'/r6/instances'` |
| | 待办任务 | `/r6/tasks/` | `'/r6/tasks'` |
| | 消息中心 | `/r6/notifications/` | `'/r6/notifications'` |
| 统计分析 | 指标看板 | `/r7/dashboard/` | `'/r7/dashboard'` |
| | 指标与报表 | `/r7/metrics/` | `'/r7/metrics' or '/r7/reports'` |
| 平台 | API 文档 | `/r8/docs/` | `'/r8/' or path[:5] == '/api/'` |
| | 运维状态 | `/r9/status/` | `'/r9/'` |

**服务器端授权才是权威**：侧边栏不做隐藏式"安全"，直接访问 URL 由视图的
`roles_required` 判定（测试 `test_anonymous_denied_on_new_pages` 覆盖）。

## 5. 身份展示

```django
{{ request.user.display_name|default:request.user.login_name }}
```

- **不使用** `request.user.username`：`Account` 模型没有该字段，模板会静默失败
  （此前已实际踩坑）。
- `request.user` 由 `AuthenticationMiddleware` + `r21_account.AccountBackend` 解析；
  本隔离配置下 `request.account` 未被 r22 中间件注入，因此以 `request.user` 为准。
- `SimpleLazyObject` 场景由浏览器 E2E 覆盖（U8）。

## 6. 响应式策略

| 断点 | 侧边栏 | 布局 |
|---|---|---|
| > 900px | 常驻 236px | 侧栏 + 主区 |
| ≤ 900px | 固定定位 + `translateX(-100%)`，抽屉 | 抽屉 + 遮罩 |
| ≤ 600px | 同上 | 单列、表格横向滚动、KPI 两列 |

抽屉行为（`static/js/r10.js`）：
- 点击 `#sm-drawer-toggle` 打开；点击遮罩或 `Escape` 关闭；
- 打开时焦点移到第一个可聚焦元素，`Tab` 在抽屉内循环（焦点陷阱）；
- 关闭后焦点回到触发按钮；
- `aria-expanded` / `aria-hidden` 同步。

## 7. 隔离与安全

- 所有页面运行在 `smass.settings_r10` / 库 `smass_r10_release`；
- 正式 `smass` **零写入**；
- `AUTH_USER_MODEL` 未改；
- 不引入 CDN、不新增前端依赖。
