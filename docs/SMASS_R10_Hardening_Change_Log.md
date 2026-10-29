# SMASS R10 Hardening Change Log（H0–H9）

基线：`488f6c5`　分支：`feat/smass-r4-r10-integrated-platform`

## 1. 提交序列

| SHA | 类型 | 内容 |
|---|---|---|
| `f7592fb` | fix | H1 恢复真实改密视图 + 首次登录强制改密 |
| `cef2e82` | fix | H2 MySQL 生成列唯一约束 |
| `0029230` | fix | H3 WebKit 500 根因 + READ COMMITTED |
| `c888839` | feat | H4 可访问性加固 |
| `1085bb8` | feat | H5 26 表升级与恢复演练 |
| `4d17add` | fix | H6 集成安全（修 2 个跨 settings 回归） |
| `7f7c84a` | feat | H7 三浏览器 E2E + 并发 |
| 本提交 | feat | H8 全量回归 + 打包门禁 |

## 2. 新增文件

### 迁移
- `r21_account/migrations/0002_active_role_unique.py`
- `smass_workflow/migrations/0003_open_task_unique.py`

### 脚本
- `scripts/r10_uniqueness_precheck.py` — 重复数据只读预检
- `scripts/r10_upgrade_clone_drill.py` — schema-only 升级 + 备份恢复
- `scripts/r10_full_regression.py` — 全量回归测量
- `scripts/r10_release_hardening_gate.py` — 三层门禁（结构/证据/产物）
- `scripts/r10_browser_probe.py` — 真实服务器三引擎探针

### 配置
- `smass/settings_h5.py` — 演练专用（`smass_h5_` 前缀）

### 测试
- `smass_operations/tests/test_r10_h1_password.py`（18）
- `smass_operations/tests/test_r10_h2_uniqueness.py`（10）
- `smass_operations/tests/test_h3_repro.py`（2）
- `smass_operations/tests/test_r10_h4_a11y.py`（15）
- `smass_operations/tests/test_r10_h6_security.py`（27）
- `smass_operations/tests/test_r10_h7_e2e.py`（6）

### 文档
- `SMASS_R10_Password_Lifecycle_Report.md`
- `SMASS_R10_Uniqueness_Enforcement_Report.md`
- `SMASS_R10_WebKit_Root_Cause.md`
- `SMASS_R10_Accessibility_Audit.md`
- `SMASS_R10_Existing_DB_Upgrade_Drill.md`
- `SMASS_R10_Security_Regression.md`
- `SMASS_R10_E2E_Cross_Browser.md`
- `SMASS_R10_Hardening_Execution_Report.md`
- `SMASS_R10_Hardening_Change_Log.md`
- `SMASS_R10_Release_Go_NoGo.md`（H9）
- `docs/dsh_run/R10_HARDENING_{TASKS,STATE,RESUME,COMMAND_LOG,DECISIONS}.json|md`

## 3. 修改的既有文件

| 文件 | 变更 |
|---|---|
| `smass/urls_r10.py` | 改密路由恢复真实视图；`export/` 排到 `<student_no>` 之前 |
| `smass/settings_r10.py` | 加 READ COMMITTED 隔离级别 |
| `r21_account/models.py` | 移除条件 `UniqueConstraint`，注明由迁移 0002 保证 |
| `smass_workflow/models.py` | 同上（迁移 0003） |
| `smass_analytics/ui_views.py` | 补 dashboard JSON 分支 |
| `templates/r21/login.html` | `<label for>` 绑定 + `<h1>` |
| `templates/r21/change_password.html` | `<h1>` |
| `templates/r21/home.html` | `<h1>` |
| `templates/r10/base.html` | 加 skip-to-content |
| `static/css/r10.css` | `.sm-skip` + `forced-colors` + 640px 断点 |
| 8 个表单模板 | 23 个字段补 `aria-invalid` + `aria-describedby` |
| `smass_operations/tests/test_r10_u8_browser.py` | WebKit 范围按 R-15 调整 |

## 4. 修复的缺陷（按发现顺序）

| # | 缺陷 | 性质 | 发现于 |
|---|---|---|---|
| 1 | `/r21/change-password/` 是 RedirectView，强制改密完全失效 | **P0 安全** | H0 审计 |
| 2 | `AccountRole` 的条件唯一约束在 MySQL 从未创建 | **P0 数据完整性** | H2 实测 `SHOW INDEX` |
| 3 | `ApprovalTask` 同上 | **P0** | H2 |
| 4 | `/r21/login/` 在 WebKit 下 500（Django `update_last_login` + REPEATABLE READ） | P1 | H3 复现 |
| 5 | 无 skip-to-content | P1 可访问性 | H4 审计 |
| 6 | 3 个模板缺 `<h1>` | P1 | H4 |
| 7 | 0 个 `aria-describedby`（错误与字段无关联） | P1 | H4 |
| 8 | `/r4/students/export/` 被 `<student_no>` 抢占 → 404 | **P1 功能** | H6（仅 r10 暴露） |
| 9 | `/r7/dashboard/` 丢 JSON 分支 → AJAX 返回 HTML | P1 | H6（仅 r10 暴露） |
| 10 | 登录页 `<label>` 缺 `for` | P1 | H7 连带发现 |

## 5. 方法学修正（记录在 decisions）

| ID | 内容 |
|---|---|
| HD-001 | RedirectView 顶替真实视图——占位实现可能只是为了绕过测试，要审路由不只看视图 |
| HD-002 | 弱密码断言改为行为断言（哈希不变），不依赖错误文案语言 |
| HD-003 | 其他会话失效由 Django `_auth_user_hash` 保证，无需自建 |
| HD-004 | 生成列 + 唯一索引实现"单 active"（利用 NULL 互不相等） |
| HD-005 | WebKit 500 根因是 `update_last_login` + REPEATABLE READ |
| HD-006 | 200% 缩放用 640×430 视口，不是 `device_scale_factor` |
| HD-007 | 高对比分 CSS 层与运行时模拟两层，真实 Windows 主题标 PARTIAL |
| HD-008 | axe-core 无离线包，不引未审计依赖，标 NOT RUN |
| HD-009 | 升级演练必须复制 `django_migrations` 记录，否则 1050 冲突 |
| HD-010 | schema-only 克隆只证结构，数据迁移需 PII 授权 |
| HD-011 | 跨 settings 回归必要性（同代码不同 URLconf 行为不同） |
| HD-012 | 学生导出 403 是正确设计 |
| HD-013 | R-15 准确性质是同进程累积，不是类内多测试 |

## 6. 未修改（安全边界）

| 项 | 状态 |
|---|---|
| `smass` 数据库 | **只读**，26 表 / 1-3-2 未变 |
| `AUTH_USER_MODEL` | **未改**（`auth.User`） |
| `app01` 应用代码 | **未改** |
| MySQL 全局配置 | **未改**（只改隔离 settings 的会话级隔离级别） |
| 既有数据库/账号 | **未删除** |
| 远程 Git | **未推送** |
| 生产部署 | **未执行** |
| 仓库内凭据/哈希/备份 | **无**（扫描 PASS） |

## 7. 测试数变化

| 阶段 | 总数 |
|---|---|
| R10 UI/UX 完成（`488f6c5`） | 733 |
| H8 实测 | **811** |

新增 78 例，全部为硬化阶段的垂直切片测试。
