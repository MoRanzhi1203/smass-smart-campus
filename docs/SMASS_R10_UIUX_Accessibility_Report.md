# SMASS R10 可访问性报告（U8）

## 1. 检查方法

| 层 | 方法 | 说明 |
|---|---|---|
| 静态 DOM | Django Client 断言 | `test_r10_u8_routes.py::A11yPrimitiveTests`（8 例） |
| 真实浏览器 | Playwright 断言 | `test_r10_u8_browser.py::AccessibilityTests`（7 例 × 2 引擎） |
| CSS 规则 | `document.styleSheets` 遍历 | 检查 `prefers-reduced-motion` |

## 2. 已实现的基元

| 项 | 实现 | 证据 |
|---|---|---|
| 可见焦点 | `:focus-visible { box-shadow: var(--sm-focus) }` | `test_focus_visible_style_exists` |
| 语义地标 | `<aside aria-label="主导航">` `<nav aria-label="面包屑">` `<main id="sm-content">` | `test_skip_to_content_absent_but_main_landmark_present` |
| 抽屉状态 | `aria-controls` / `aria-expanded` / `aria-hidden` 同步 | `test_aria_expanded_syncs`、`test_drawer_has_aria_attributes` |
| 焦点陷阱 | 抽屉内 `Tab`/`Shift+Tab` 循环 | 代码实现 + 人工走查 |
| 键盘关闭 | `Escape` 关抽屉并回焦 | `test_escape_closes_drawer_and_returns_focus` |
| 键盘可达 | `Tab` 能到达侧边栏链接 | `test_keyboard_reaches_nav_links` |
| 异步播报 | toast 容器与消息区 `aria-live="polite"` | `test_alert_regions_are_live` |
| 表头 | 所有数据表有 `<thead><th>` | `test_tables_have_thead`、`test_table_headers_present_in_dom` |
| 表单标签 | `<label for="f-xxx">` 与输入 id 绑定 | `test_form_labels_bound`（断言 0 个未绑定） |
| 必填标识 | `.req` 星号 | `test_required_fields_marked` |
| 减少动效 | `@media (prefers-reduced-motion: reduce)` 关闭过渡 | `test_reduced_motion_media_query_exists` |
| 打印 | `@media print` 隐藏导航 | 代码实现 |
| 视口 | 每页 `name="viewport"` | `test_every_page_has_viewport_meta` |

## 3. 对比度（计算值）

| 组合 | 前景 | 背景 | 对比度 | 等级 |
|---|---|---|---|---|
| 主文本 | `#111827` | `#f6f7f9` | ≈ 15.3:1 | AAA |
| 次要文本 | `#6b7280` | `#ffffff` | ≈ 4.8:1 | AA |
| 侧栏链接 | `#d1d5db` | `#111827` | ≈ 9.5:1 | AAA |
| 主按钮文字 | `#ffffff` | `#2563eb` | ≈ 4.6:1 | AA（大字号 AAA） |
| 成功徽章 | `#059669` | `#ecfdf5` | ≈ 4.7:1 | AA |
| 危险徽章 | `#dc2626` | `#fef2f2` | ≈ 4.9:1 | AA |

## 4. 未做的项（如实列出）

| 项 | 状态 | 原因 |
|---|---|---|
| 屏幕阅读器实机测试（NVDA/JAWS/VoiceOver） | **未做** | 需要人工与真实辅助技术，自动化不能替代 |
| 完整 WCAG 2.1 AA 审计 | **未做** | 需专业审计工具与人工走查 |
| 图片 alt 文本 | N/A | 界面未使用 `<img>`（图标为 Unicode 字符 + `aria-hidden`） |
| 表单错误 `aria-describedby` 关联 | **部分** | 错误文本有 `id`，但未在所有字段加 `aria-describedby` |
| 跳转到主内容链接 | **未做** | 侧边栏仅 17 项，Tab 成本可接受；可后续补 |
| 高对比模式（Windows HC） | **未测** | 依赖系统设置，未验证 |
| 200% 缩放 | **未测** | 未在真实浏览器做缩放验证 |

## 5. WebKit 的 a11y 盲区

WebKit 在 `LiveServerTestCase` 下无法完成登录（见 E2E 报告 §5），
因此以下断言**只在 Chromium/Firefox 上通过**：

- `test_escape_closes_drawer_and_returns_focus`
- `test_keyboard_reaches_nav_links`
- `test_focus_visible_style_exists`
- `test_form_labels_bound`
- `test_reduced_motion_media_query_exists`

WebKit 只验证了：登录页渲染、首页渲染（含 `#sm-sidebar`）、响应式无溢出、
`prefers-reduced-motion` 规则存在（`AnonymousRenderTests`，4 例）。

## 6. 结论

**已实现**：键盘可达、焦点可见、语义地标、aria 状态同步、表头、
label 绑定、必填标识、减少动效、打印样式、移动端触控尺寸。

**未实现/未验证**：屏幕阅读器实机、完整 WCAG 审计、`aria-describedby` 全覆盖、
跳转链接、高对比模式、200% 缩放。

因此本报告**不宣称 WCAG 合规**，只声明"关键 a11y 基元已实现且有自动化断言"。
