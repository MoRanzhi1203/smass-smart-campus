# SMASS R10 设计系统（U2）

实现文件：`static/css/r10.css`（令牌 + 组件）· `static/js/r10.js`（交互）

## 1. 设计令牌

| 类别 | 变量 | 值 |
|---|---|---|
| 主色 | `--sm-primary` | `#2563eb` |
| 主色悬停 | `--sm-primary-hover` | `#1d4ed8` |
| 主色浅底 | `--sm-primary-soft` | `#eff6ff` |
| 画布 | `--sm-canvas` | `#f6f7f9` |
| 卡片 | `--sm-surface` | `#ffffff` |
| 边框 | `--sm-border` / `--sm-border-strong` | `#e5e7eb` / `#d1d5db` |
| 文本 | `--sm-text` / `-muted` / `-faint` | `#111827` / `#6b7280` / `#9ca3af` |
| 成功 | `--sm-success` / `-soft` | `#059669` / `#ecfdf5` |
| 警告 | `--sm-warning` / `-soft` | `#b45309` / `#fffbeb` |
| 危险 | `--sm-danger` / `-soft` | `#dc2626` / `#fef2f2` |
| 信息 | `--sm-info` / `-soft` | `#0369a1` / `#f0f9ff` |
| 圆角 | `--sm-radius` / `-sm` | `8px` / `6px` |
| 间距 | `--sm-1..6` | 4/8/12/16/24/32 px |
| 焦点 | `--sm-focus` | `0 0 0 3px rgba(37,99,235,.35)` |
| 侧栏宽 | `--sm-sidebar-w` | `236px` |
| 顶栏高 | `--sm-topbar-h` | `56px` |

## 2. 组件清单

| 组件 | Class / 标记 | 用途 |
|---|---|---|
| 外壳 | `.sm-shell` `.sm-sidebar` `.sm-main` `.sm-topbar` `.sm-content` | 页面骨架 |
| 导航 | `.sm-nav-group` `.sm-nav-label` `.sm-nav-link` `.is-active` | 分组导航与高亮 |
| 面包屑 | `.sm-breadcrumb` + `.sep` + `.current` | 路径指示 |
| 用户区 | `.sm-user` `.sm-avatar` | 身份与登出 |
| 抽屉 | `#sm-drawer-toggle` `#sm-backdrop` `.is-open` | 移动端导航 |
| 页头 | `.sm-page-head` `.sm-title` `.sm-subtitle` `.sm-page-actions` | 标题与操作区 |
| 卡片 | `.sm-card` `.sm-card-head` `.sm-card-body`（`.is-flush`） | 内容分区 |
| 表格 | `.sm-table-wrap` `.sm-table`（`td.is-num` `.sm-mono`） | 数据列表、移动横向滚动 |
| 徽章 | `.sm-badge` + `.is-success/warning/danger/info/primary` | 状态标记 |
| 表单 | `.sm-form` `.sm-field` `.sm-label` `.req` `.sm-help` `.sm-error` `.sm-form-row` | 表单布局与校验 |
| 按钮 | `.sm-btn` + `.is-primary/danger/ghost/sm` | 操作 |
| 反馈 | `.sm-alert` + `.is-*`、`.sm-toast-host` `.sm-toast` | 页内提示与轻提示 |
| 空态 | `.sm-empty` `.sm-empty-icon` `.sm-empty-title` `.sm-empty-desc` | 无数据 |
| 加载 | `.sm-spinner` `.sm-loading-overlay` `.sm-relative` | 异步等待 |
| KPI | `.sm-kpi-grid` `.sm-kpi` `.sm-kpi-label` `.sm-kpi-value` `.sm-kpi-unit` | 指标卡 |

## 3. JS 能力（`window.SM`）

| 方法 | 说明 |
|---|---|
| `SM.toast(msg, kind)` | 右下角轻提示，4 秒自动消失，`aria-live=polite` |
| `SM.confirm(msg, opts)` | Promise 化确认框；`Escape` 取消、`Tab` 循环、点遮罩取消 |
| `SM.request(url, opts)` | 自动带 `X-CSRFToken` / `X-Requested-With`，返回 `{ok,status,data}` |
| `SM.csrfToken()` | 从隐藏 input 或 cookie 取 token |
| `SM.openDrawer()` / `closeDrawer()` | 抽屉控制 |

声明式绑定：
- `form[data-sm-form]`：提交时自动禁用按钮并显示 spinner，防重复提交；
- `[data-sm-confirm="文案"]`：点击先确认再执行（`data-sm-danger="1"` 用红色按钮）。

## 4. 可访问性

| 项 | 实现 |
|---|---|
| 可见焦点 | `:focus-visible` 统一 3px 蓝色环 |
| 语义标签 | `<aside aria-label>` `<nav aria-label>` `<main>` |
| 抽屉 | `aria-controls` / `aria-expanded` / `aria-hidden` 同步 |
| 焦点陷阱 | 抽屉内 `Tab`/`Shift+Tab` 循环 |
| 键盘关闭 | `Escape` 关抽屉与确认框 |
| 异步播报 | toast 容器与消息区 `aria-live="polite"` |
| 减少动效 | `@media (prefers-reduced-motion: reduce)` 关闭过渡 |
| 对比度 | 主文本 `#111827` on `#f6f7f9`（≈15:1）；侧栏 `#d1d5db` on `#111827`（≈9:1） |
| 打印 | `@media print` 隐藏导航 |

## 5. 使用约定

1. 页面**只写** `{% block content %}` 内容，不写 `<head>` / 导航；
2. 列表统一 `.sm-card` + `.sm-table-wrap` + `.sm-table`；
3. 空数据统一 `.sm-empty`，不写"暂无数据"裸文本；
4. 提交类表单加 `data-sm-form`；
5. 危险操作加 `data-sm-confirm` 与 `data-sm-danger="1"`；
6. 数字列加 `.is-num`（等宽对齐），标识符加 `.sm-mono`。
