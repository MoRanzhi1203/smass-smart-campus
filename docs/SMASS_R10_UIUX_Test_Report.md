# SMASS R10 UI/UX 测试报告（U9）

- 设置：`smass.settings_r10`（部分套件用各自 `settings_r*`）
- 库：`smass_r10_release` 等隔离库
- 基线：`5b69d58`
- 执行日期：2026-10-29

## 1. 全量回归结果

| 套件 | 命令 settings | 用例 | 结果 |
|---|---|---|---|
| `smass_operations`（R9+R10 UI/UX） | `settings_r10` | **217** | PASS |
| `smass_analytics`（R7） | `settings_r7` | 31 | PASS |
| `smass_organization`（R4） | `settings_r4` | 69 | PASS |
| `smass_academic`（R5） | `settings_r5` | 56 | PASS |
| `smass_workflow`（R6） | `settings_r6` | 41 | PASS |
| `smass_api`（R8） | `settings_r8` | 23 | PASS |
| `r22_account` | `settings_r22` | 94 | PASS |
| `r21_account` | `settings_r21` | 72 | PASS |
| `app01` | 正式 settings | 114 | PASS |
| `tests_e2e` | 正式 settings | 16 | PASS |
| **合计** | | **733** | **全绿** |

> `smass_operations` 217 例为默认（Chromium）模式；
> 设 `R10_BROWSER=all` 时 U8 浏览器套件扩展为 42 例（三引擎）。

## 2. 质量门禁

| 检查 | 命令 | 结果 |
|---|---|---|
| Django check | `manage.py check` | **0 issues** |
| 迁移一致性 | `makemigrations --check --dry-run` | **No changes** |
| 秘密扫描 | `scripts/r9_secret_scan.py` | **PASS**（0 生产凭据；43 处测试夹具已识别） |
| 本地 CI | `scripts/ci_local.py` | 通过 |
| 源库指纹 | `scripts/db_inspect.py` | **26 表** / Admin 1 · Student 3 · Teacher 2（未变） |

## 3. U0–U8 各片测试数

| 任务 | 测试文件 | 例数 |
|---|---|---|
| U0 | （脚本 + 文档，无测试） | — |
| U1 | `test_r10_shell.py::SidebarTests` | 6 |
| U2 | `test_r10_shell.py::DesignSystemTests` | 4 |
| U3 | `test_r10_u3_r4.py` | 24 |
| U4 | `test_r10_u4_r5.py` | 26 |
| U5 | `test_r10_u5_r6.py` | 23 |
| U6 | `test_r10_u6_r7.py` | 24 |
| U7 | `test_r10_u7_r8r9.py` | 26 |
| U8 | `test_r10_u8_routes.py` + `test_r10_u8_browser.py` | 21 + 42 |
| 兼容性调整 | `test_r10_nav.py`、`test_r10_release.py`、`test_r10_shell.py` | 6 + 10 + 5 |

## 4. 真实浏览器证据

| 类型 | 数量 | 位置 |
|---|---|---|
| 截图 | **23 张** | `docs/screenshots/r10_uiux/` |
| 三引擎探针 | 3 引擎 × 11 步 | `scripts/r10_browser_probe.py` → `ok: true` |

截图覆盖：导航、组织、学生、导入（预览态）、教学班、任课分配、名册、
流程定义（真实创建 4 节点）、看板、报表、API 文档、运维状态、移动抽屉。

## 5. U9 期间发现并修复的 2 个回退

全量回归暴露了 U6 引入的两处破坏——这正是"只跑 operations 不够"的证明：

### 回退 1：模板改了，`urls_r7` 的旧视图没改

- 现象：`test_dashboard_renders_values` 断言 `org_units_total` 但页面渲染出 `data-metric=""`
- 根因：`smass.settings_r7` 的 `ROOT_URLCONF='smass.urls_r7'` 指向**旧视图**
  `smass_analytics.views.dashboard`（返回 `meta`，含 `metric` 键），
  而模板已被 U6 改成期望 `code`
- 修法：旧视图补齐 `code` / `description` / `unit` / `version` / `suppressed`

### 回退 2：JSON 响应丢了 `metric` 键

- 现象：`test_r7_browser.py` 报 `KeyError: 'metric'`
- 根因：新结构只提供 `code`，旧浏览器测试依赖 `metric`
- 修法：响应同时提供 `metric` 与 `code`（向后兼容）

**教训**：改共享模板时，必须同时检查**所有 settings 下的 ROOT_URLCONF**。

## 6. 测试可信度说明

| 项 | 说明 |
|---|---|
| 断言级别 | 大多数用例断言**数据库状态**或**HTTP 状态码**，少量断言 DOM 结构 |
| 是否只有 DOM 断言 | 否。U3/U4/U5 均有"提交后查 DB"的用例 |
| WebKit 覆盖 | 单测环境下仅匿名渲染（4 例）；完整流程由真实服务器探针覆盖 |
| 重试 | 仅 R2.1 遗留的一处登录重试（有界，仍会 FAIL）；本轮未新增重试 |
| 跳过的测试 | WebKit 的表单流程在单测环境下 skip，原因见 E2E 报告 §5 |

## 7. 结论

**733 例全绿，0 失败，0 错误。** 两处 U9 发现的回退已修复并复测通过。
未发现新的高危缺陷。
