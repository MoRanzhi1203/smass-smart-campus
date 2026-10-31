# 02 UI 设计系统

> 目标：**Modern Campus SaaS** —— 清爽、专业、克制、现代、高可读性。
> 实现：`static/workspace/app.css`（单文件、三端共用）。
> 验收：`scripts/ui_visual_check.py`（12 视口截图 + 横向溢出检测）。

---

## 1. 设计令牌

| 类别 | 令牌 | 值 |
|---|---|---|
| 品牌 | `--smass-brand-900` | `#14283F`（侧栏/深色区） |
| 品牌 | `--smass-brand-700` | `#1D4ED8` |
| 品牌 | `--smass-brand-600` | `#2563EB`（主操作） |
| 品牌 | `--smass-brand-50` | `#EFF6FF`（浅底） |
| 辅助 | `--smass-accent-600` | `#0D9488`（教师端） |
| 辅助 | `--smass-accent-50` | `#F0FDFA` |
| 表面 | `--smass-surface` | `#FFFFFF` |
| 页面 | `--smass-page-bg` | `#F4F7FB` |
| 弱表面 | `--smass-surface-muted` | `#F8FAFC` |
| 文本 | `--smass-text-primary` | `#0F172A` |
| 文本 | `--smass-text-secondary` | `#475569` |
| 文本 | `--smass-text-muted` | `#64748B` |
| 边框 | `--smass-border` | `#E2E8F0` |
| 语义 | `--smass-success` | `#15803D` |
| 语义 | `--smass-warning` | `#B45309` |
| 语义 | `--smass-danger` | `#DC2626` |
| 圆角 | `--smass-radius-sm/md/lg` | 6 / 10 / 14 px |
| 间距 | `--smass-space-1…8` | 4/8/12/16/20/24/32 px |

令牌与既有 `--ws-*` 同源（`--smass-*` 引用 `--ws-*`），模板无需改动即可获得新视觉。

---

## 2. 三端角色辅助色

| 端 | 主色 | 浅底 | 用途 |
|---|---|---|---|
| 学生 | `#2563EB` | `#EFF6FF` | 主按钮、激活导航 |
| 教师 | `#0D9488` | `#F0FDFA` | 主按钮、激活导航 |
| 管理 | `#334155` | `#F1F5F9` | 主按钮、激活导航（深海蓝灰，克制） |

实现：`body[data-workspace="student|teacher|admin"]` 切换 `--ws-accent` 系列，
**同一套 CSS**，不引入第二套框架。

---

## 3. 布局基线

| 项 | 值 |
|---|---|
| 顶栏高度 | 62px，白底、1px 底边、无阴影 |
| 侧栏宽度 | 248px（移动端抽屉 272px） |
| 内容区内边距 | 桌面 24/28px；≤1100px 20/18px；≤720px 16/14px |
| 卡片圆角 | 10px（`--smass-radius-md`） |
| 卡片阴影 | `0 1px 2px + 0 1px 3px`，不叠加多层 |
| 按钮高度 | 34px（`is-sm` 28px） |
| 表单控件 | 38px |
| 表格行高 | 约 44px，表头 12px 字号 |
| 模块间距 | 16–24px |

移动端：侧栏变抽屉（`app.js` 已有），表格横向滚动，不整页溢出。

---

## 4. 字体与图标

- 字体栈：`"Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif`；
- 数字使用 `font-variant-numeric: tabular-nums`（统计值、表格数字）；
- 图标：`base.html` 内联 19 个线性 SVG symbol（Lucide 风格），通过
  `<svg><use href="#ws-i-*"></use></svg>` 复用；
- 图标不替代按钮文本；图标按钮必须有 `aria-label`。

---

## 5. 组件状态

| 组件 | 类名 | 状态 |
|---|---|---|
| AppShell | `.ws-app` | 已有 |
| Header | `.ws-topbar` | 已有（62px / 白底） |
| Sidebar | `.ws-sidebar` | 已有（深蓝 / 激活左侧 3px 条） |
| NavigationGroup | `.ws-nav-label` + `.ws-nav-link` | 已有 |
| PageHeader | `.ws-page-head` | 已有 |
| StatCard | `.ws-stat` | 已有（26px 数字） |
| DataTable | `.ws-table` | 已有（固定表头样式、hover） |
| FilterBar / Search | `.ws-filters` / `.ws-input` | 已有基础 |
| Pagination | — | **待补** |
| DetailDrawer / Modal | — | **待补** |
| FormField | `.ws-field` / `.ws-input` | 已有 |
| StatusBadge | `.ws-badge.is-*` | 已有（圆点 + 文本，不单靠颜色） |
| EmptyState | `.ws-empty` | 已有（图标 + 标题 + 说明） |
| LoadingState | — | 待补（当前为服务端渲染） |
| ErrorState | `.ws-alert.is-error` | 已有 |
| Toast | — | 待补（当前用 messages） |
| ConfirmDialog | — | 待补 |
| Tabs | — | 待补 |
| NotificationCenter | `/notifications/` | 已有页面 |
| RoleSwitcher | `.ws-switcher` | 已有 |

---

## 6. 交互与可访问性规则

1. 所有可聚焦控件有 `:focus-visible` 2px 主色描边（已统一）；
2. 状态不只靠颜色：徽章带圆点与文字；
3. 表头 `th` 有语义；按钮使用原生 `<button>`；
4. 表单控件 38px 高，标签与输入关联（后续逐页核查）；
5. 移动端操作不依赖 hover；
6. `prefers-reduced-motion` 关闭动画；
7. 跳过导航链接 `.ws-skip`；
8. 侧栏抽屉 `aria-expanded` / `aria-controls`。

---

## 7. 禁止项（已执行检查）

| 禁止 | 现状 |
|---|---|
| 大面积高饱和渐变 | 已移除 hero/登录页渐变与光斑（`grep gradient` 为空） |
| 荧光色 | 无 |
| 玻璃拟态 | 无 |
| 复杂背景纹理 | 无 |
| 多套配色 | 单套令牌 + 三端辅助色 |
| emoji 图标 | 无（使用 SVG） |
| 滥用动画 | 仅抽屉/切换器过渡，且可被 reduced-motion 关闭 |

---

## 8. 验收方法

```powershell
& $py scripts\ui_visual_check.py --base http://127.0.0.1:8050
```

- 角色：student / teacher / admin；
- 视口：390×844、768×1024、1366×768、1920×1080；
- 指标：`scrollWidth > clientWidth` 即失败、计算后的 `--ws-accent`、卡片/表格/按钮数量；
- 截图：`.local/evidence/v2/screenshots/`；
- 本轮结果：**12/12 通过，0 横向溢出**。

后续批次补充：125%/150% 缩放、长中文数据、空/错/无权限状态截图。
