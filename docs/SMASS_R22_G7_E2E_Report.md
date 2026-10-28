# SMASS R2.2 G7 浏览器 E2E 报告（E2E Report）

- 测试文件：`r22_account/tests/test_g7_browser.py`
- 运行：`manage.py test r22_account.tests.test_g7_browser --settings=smass.settings_r22`
- 结果：**8/8 PASS**（22.231 s）
- 浏览器：Chromium（Playwright 1.64.1，headless）
- 隔离：`test_smass_r22_proto`；正式入口未改

## 1. 覆盖矩阵

| # | 场景 | 视口 | 结果 |
|---|---|---|---|
| 1 | 管理员登录 + 身份探针 | desktop 1280×860 | PASS |
| 2 | 教师登录 + 身份探针 | mobile 390×844 | PASS |
| 3 | 学生登录 + 身份探针 | tablet 768×1024 | PASS |
| 4 | 首次登录强制改密（临时口令 → 改密 → 进入首页） | desktop | PASS |
| 5 | 未登录访问 `/legacy-parity/` 被拒并跳登录 | desktop | PASS |
| 6 | **account 身份不能访问 legacy 路由** | desktop | PASS |
| 7 | 停用账号无法登录（统一错误提示） | desktop | PASS |
| 8 | 匿名访问受保护 JSON 探针 → 403 | desktop | PASS |

## 2. 本轮发现的真实缺陷（已修复）

**路由策略拒绝时的跳转目标错误**：

```
修复前：_deny() → redirect('/login/')   # /legacy-parity/ 触发
修复后：_deny() → redirect('/r21/login/')
```

原因：`urls_r22` 只挂载了 `/r21/login/`，`/login/` 在隔离配置下不存在 → 404。
浏览器测试首次运行即暴露该问题（`'/r21/login/' not found in 'http://localhost:58023/login/'`）。

修复位置：`r22_account/middleware.py::RoutePolicyMiddleware._deny`。

## 3. 旧 URL 迁移对照（逐页清单）

| 旧路由 | 兼容层行为 | 覆盖状态 |
|---|---|---|
| `/admin/*` | 策略允许 `legacy`/`dual`；`app01` 视图未在 `urls_r22` 挂载 | **部分**：策略已验，页面未接入 |
| `/student/*` | 同上 | **部分** |
| `/teacher/*` | 同上 | **部分** |
| `/login/`（旧登录页） | 不存在于隔离配置 | **不可运行**（有意为之，避免双登录入口） |
| `/legacy-parity/`（探针） | 可运行 | PASS |

> **未为了让 E2E 通过而修改 `app01` 正式路由**。`app01` 仍使用 `session['info']`，本轮零改动。

## 4. 跨浏览器 / 视口

| 浏览器 | 状态 |
|---|---|
| Chromium | PASS（全部 8 例） |
| Firefox | **NOT RUN**（未安装） |
| WebKit | **NOT RUN**（未安装） |

视口：desktop / tablet / mobile 三档均至少覆盖一次。

## 5. 失败产物

本轮最终无失败用例。首轮的失败信息保留在命令日志中（未生成截图，因为失败是断言级而非视觉级）。

## 6. 未做

| 项 | 状态 |
|---|---|
| 多标签页 / 刷新保持 | NOT RUN |
| 角色撤销后的浏览器会话 | NOT RUN（服务层已覆盖） |
| 对象级数据隔离的浏览器验证 | NOT RUN（服务层已覆盖） |
| 视觉回归（截图对比） | NOT RUN |
