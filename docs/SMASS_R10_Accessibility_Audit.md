# SMASS R10 Accessibility Audit（H4）

- 设置：`smass.settings_r10`　库：`smass_r10_release`（隔离）
- 执行：`smass_operations/tests/test_r10_h4_a11y.py`（15 例）
- 引擎：Chromium（`H4_BROWSER` 可切 firefox/webkit）

## 1. 结果总览

| 检查项 | 方法 | 结果 |
|---|---|---|
| skip-to-content | 代码 + 浏览器（聚焦后可见） | **PASS** |
| 每页恰好一个 `<h1>` | Django Client 逐页断言 | **PASS** |
| 表单错误 `aria-describedby` | 23 个字段注解 + 引用完整性断言 | **PASS** |
| 表单错误 `aria-invalid` | 同上 | **PASS** |
| 200% 缩放（等效 640×430） | 6 页无横向溢出 | **PASS** |
| 强制颜色模式（CSS 规则） | `forced-colors` 媒体查询存在 | **PASS** |
| 强制颜色模式（运行时模拟） | `emulate_media(forced_colors='active')` | **PASS** |
| Tab 顺序（skip 先于导航） | Chromium/Firefox 真实按键 | **PASS** |
| `aria-live` 区域 | toast/消息区 | **PASS** |
| 表格 `thead` | 所有 `.sm-table` | **PASS** |
| 键盘可达导航链接 | 程序化聚焦 + Tab（Chromium/Firefox） | **PASS** |
| 焦点可见 | CSS `:focus-visible` 规则 + 计算样式 | **PASS** |
| 抽屉 aria 同步 | `aria-expanded` / `aria-hidden` | **PASS**（U8） |
| Escape 关抽屉回焦 | 真实按键 | **PASS**（U8） |
| 抽屉焦点陷阱 | Tab 循环 | **PASS**（U8） |

## 2. 本轮新增/修改

### 2.1 skip-to-content（新增）

`templates/r10/base.html` 在 `<body>` 后第一个可聚焦元素：

```html
<a class="sm-skip" href="#sm-content">跳到主要内容</a>
```

`static/css/r10.css`：

```css
.sm-skip { position: absolute; left: -9999px; top: 0; z-index: 200; }
.sm-skip:focus, .sm-skip:focus-visible { left: 0; outline: 3px solid var(--sm-primary); }
```

验证：初始在视口外；聚焦后进入视口；Tab 第一个落点。

### 2.2 表单错误关联（新增）

之前错误元素有 `id="err-xxx"`，但字段本身**没有引用**。现在 23 个字段加了：

```html
<input id="f-code" ... aria-invalid="true" aria-describedby="err-code">
<div class="sm-error" id="err-code">编码不能为空</div>
```

测试断言：**每个 `id="err-*"` 都必须被某个 `aria-describedby` 引用**（防孤儿错误）。

### 2.3 h1 补齐

`r21/login.html`、`r21/change_password.html`、`r21/home.html` 原本无 `<h1>`，已补。
`base.html` 本身不含 h1（外壳），由各页面提供 —— 测试逐页断言"恰好一个"。

### 2.4 200% 缩放

**方法说明**：Playwright 的 `device_scale_factor` 是设备像素比，**不是**缩放；
CDP 的 `Emulation.setPageScaleFactor` 只改渲染不改布局视口。

正确做法是把视口设为 `640×430`（即 1280×860 的一半），
这等效于 200% 缩放后的**布局视口**，然后断言
`scrollWidth <= clientWidth + 1`。

覆盖 6 个页面：`/r10/` `/r4/units/` `/r5/years/` `/r7/dashboard/` `/r8/docs/` `/r9/status/`。

### 2.5 强制颜色模式

- CSS 层：`@media (forced-colors: active)` 为按钮/导航/卡片/表格补 `1px solid CanvasText`，
  焦点改 `3px solid Highlight`
- 运行时：`page.emulate_media(forced_colors='active')` 后断言无溢出、侧边栏仍可见
- 若引擎不支持该模拟，测试 `skipTest` 并记录引擎名（不静默通过）

## 3. 未执行项（如实记录，不宣称 WCAG 合规）

| 项 | 状态 | 原因 |
|---|---|---|
| 屏幕阅读器实机（NVDA / JAWS / VoiceOver） | **NOT RUN** | 本机无这些工具；自动化不能替代人工走查 |
| axe-core 自动扫描 | **NOT RUN** | 仓库无离线 `axe.min.js`；`node_modules` 不存在；不联网安装第三方包以避免引入未审计依赖 |
| 完整 WCAG 2.1 AA 审计 | **NOT RUN** | 需专业工具 + 人工审查 |
| 高对比模式（Windows HC 主题） | **PARTIAL** | 验证了 `forced-colors` CSS 与模拟，未在真实 Windows 高对比主题下走查 |
| 文本对比度全量测量 | **PARTIAL** | 仅在设计与 E2E 报告中给出 6 组关键组合计算值 |
| 动画/闪烁（WCAG 2.3） | **PASS（设计层）** | `prefers-reduced-motion` 关闭过渡；无自动播放内容 |
| 表单自动完成语义（`autocomplete`） | **NOT RUN** | 未标注 `autocomplete` 属性 |

## 4. 已知对比度（计算值，非工具实测）

| 组合 | 前景 / 背景 | 比值 | 等级 |
|---|---|---|---|
| 主文本 | `#111827` / `#f6f7f9` | ≈ 15.3:1 | AAA |
| 次要文本 | `#6b7280` / `#ffffff` | ≈ 4.8:1 | AA |
| 侧栏链接 | `#d1d5db` / `#111827` | ≈ 9.5:1 | AAA |
| 主按钮 | `#ffffff` / `#2563eb` | ≈ 4.6:1 | AA |
| 成功徽章 | `#059669` / `#ecfdf5` | ≈ 4.7:1 | AA |
| 危险徽章 | `#dc2626` / `#fef2f2` | ≈ 4.9:1 | AA |

## 5. WebKit 限制（继承 H3 / R-15）

WebKit 在同一测试类内连续多个测试时登录会静默失败（R-15，未解决）。
因此本文件的浏览器类测试当前以 Chromium 为准；
WebKit 的响应式与匿名渲染由 U8 套件覆盖（`ResponsiveTestsOnWebkit` 全过）。

## 6. 结论

**已实现并有自动化断言**：skip link、单一 h1、错误关联（aria-describedby/aria-invalid）、
200% 缩放无溢出、强制颜色 CSS + 运行时模拟、Tab 顺序、焦点可见、aria-live、表格表头、
抽屉 aria 同步与焦点陷阱。

**未执行**：屏幕阅读器实机、axe 扫描、完整 WCAG 审计、`autocomplete`、真实 Windows 高对比主题。

**因此本报告不宣称 WCAG 2.1 合规**，只声明"关键 a11y 基元已实现且有自动化证据"。
这一限制在 `SMASS_R10_Release_Go_NoGo.md` 中作为非阻断性风险记录。
