# SMASS R10 Cross-Browser E2E（H7）

- 测试：`smass_operations/tests/test_r10_h7_e2e.py`
- 设置：`smass.settings_r10`（READ COMMITTED）
- 引擎：Chromium / Firefox / WebKit

## 1. 结果矩阵（按引擎与实际执行方式）

| 引擎 | 执行方式 | 场景数 | 结果 |
|---|---|---|---|
| Chromium | 单次 `manage.py test` | 6 | **6/6 PASS** |
| Firefox | 单次 `manage.py test` | 10 | **10/10 PASS** |
| WebKit | **每个场景类独立一次 `manage.py test`** | 4 | **4/4 PASS** |
| WebKit | 与其他引擎同进程（`H7_BROWSER=all`） | 4 | **2 失败**（见 §3） |

**关键澄清**：WebKit 的 4 个场景在**独立进程**下全部通过；
失败只发生在与 Chromium/Firefox 同一进程连续运行时。

这不是"跳过"，而是"用可复现的方式执行并记录实际结果"。

## 2. 场景清单

| 场景 | 覆盖 |
|---|---|
| `H7JourneyScenario` | R4 建组织 → **学生编辑 409** → R5 建课程/教学班 → R6 建流程+审批 → R7 指标 → R8 文档 → R9 状态，每步断言 DB |
| `H7ForcedPasswordScenario` | 首次登录强制改密 → 改密 → 恢复访问业务页 |
| `H7ViewportScenario` | 375×812 / 768×1024 / 1280×860 × 6 页，无横向溢出 |
| `H7MobileDrawerScenario` | 移动端抽屉开/`Escape` 关 + 空态渲染 |
| `H7ConcurrencyTests` | 5 线程并发授予角色、4 线程并发创建 open 任务 |

## 3. R-15 的准确性质（修正之前的判断）

之前（H3）记录为"WebKit 在同一测试类内连续多个测试时登录失败"。
H7 的实测**修正**了这个描述：

| 条件 | WebKit 结果 |
|---|---|
| 单类单方法，单独进程 | **PASS** |
| 四个类在同一进程依次运行（`H7_BROWSER=all`） | 2/4 失败 |
| 与 Chromium/Firefox 同进程（`H7_BROWSER=all`） | 2/4 失败 |

**结论**：触发条件是**同一测试进程内累积多个 `StaticLiveServerTestCase` 的
setUpClass/tearDownClass 循环**，不是"类内多测试"。

**可靠规避**：每个场景类用独立 `manage.py test` 调用。

**仍开着的风险**：R-15 未根治。生产形态（真实 runserver）无此问题，
`scripts/r10_browser_probe.py` 已验证三引擎 `ok: true`。

## 4. 并发测试结果

| 测试 | 方法 | 结果 |
|---|---|---|
| 5 线程并发 `grant_role` | 真实 DB 连接 + Barrier | **恰好 1 个 active** |
| 4 线程并发创建 open `ApprovalTask` | 同上 | **恰好 1 条 open** |

两者都由 H2 的生成列唯一索引在数据库层兜底，
服务层路径在冲突时抛 `IntegrityError`，测试断言最终状态正确。

## 5. 响应式结果

| 视口 | 6 页溢出检查 | 抽屉 |
|---|---|---|
| 375×812（移动） | 无溢出 | 开/Escape 关 ✓ |
| 768×1024（平板） | 无溢出 | — |
| 1280×860（桌面） | 无溢出 | 侧栏常驻 |

## 6. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 三引擎：登录、强制改密、R4 409、R5、R6、R7、R8、R9 | §2（每步断言 DB） |
| 375 / 768 / 1280 + 200% | §5（200% 见 H4：640×430 视口） |
| 键盘、移动抽屉、错误/空/加载态、焦点 | §2 抽屉 + H4 键盘/焦点 |
| 并发/竞态（唯一约束、改密会话） | §4 + H1 多会话测试 |
| 记录截图、失败红action | 截图见 `docs/screenshots/r10_uiux/`；本文件不含 PII |
| 区分 headless 与 real-runserver | §1 表头注明执行方式；真实服务器见 `r10_browser_probe.py` |
| 不得有未报告的跳过 | §1 如实列出"同进程 vs 独立进程"两种结果 |

## 7. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| WebKit 同进程连续运行 | **FAIL（已知 R-15）** | 未根治；用独立进程规避 |
| 真实多进程 API 并发压测 | **NOT RUN** | 需要多 worker 部署；本轮只做线程级并发 |
| 200% 缩放下的三引擎 | **PARTIAL** | H4 只在 Chromium 验证 |
| 移动端真实触屏手势 | **NOT RUN** | Playwright 的 `has_touch` 是模拟，非真实设备 |
