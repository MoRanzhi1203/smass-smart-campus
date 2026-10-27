# SMASS R2.1 测试报告（Test Report）

- 执行时间：2026-10-27
- 环境：conda `smass`（Python 3.12.16 / Django 5.2.17 / Pillow 13.0.0 / MySQL 8.0.18）
- R2.1 测试库：`test_smass_r21_proto`（`settings_r21` 自动建/销毁）
- 正式库 `smass`：**未参与任何 R2.1 测试写入**

## 1. 结果总览

| 套件 | 命令 | 用例 | 结果 | 耗时 |
|---|---|---|---|---|
| R2.1 全量 | `manage.py test r21_account --settings=smass.settings_r21` | **60** | **PASS 60/60** | 52.266s |
| 原有应用 | `manage.py test app01` | **114** | **PASS 114/114** | 69.204s |
| 原有 E2E | `manage.py test tests_e2e` | **16** | **PASS 16/16** | 45.866s |
| 迁移一致性（两套 settings） | `makemigrations --check --dry-run` | — | **PASS**（均 No changes） | — |
| 账号一致性 | `verify_account_consistency --strict-count` | — | **PASS** | — |
| 依赖漏洞 | `pip-audit -r requirements.txt` | — | **PASS**（0 漏洞） | — |

## 2. R2.1 用例构成（60）

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_auth_integration.py` | 13 | Backend 契约、`request.user` 是 Account、session hash、权限授权/撤销、logout |
| `test_dual_write.py` | 11 | 双写成功/哈希一致/故障注入回滚/改密/停用启用 |
| `test_password_lifecycle.py` | 16 | 强制改密中间件、临时口令、密码策略（含取消上限） |
| `test_rate_limit.py` | 8 | 同 IP 锁定、跨会话持久、跨 IP 不误锁、账号级阈值、时间窗过期 |
| `test_rbac_scope.py` | 12 | 纵向/横向越权、默认拒绝、角色撤销、伪造入参 |
| `test_browser_r21.py` | 4 | 三端强制改密浏览器流程 + 弱密码拒绝（Playwright） |

## 3. 本轮真实失败与修复

| # | 失败 | 根因 | 修复 |
|---|---|---|---|
| 1 | `makemigrations` 报 `fields.E304 Reverse accessor 'Group.user_set' clashes` | `PermissionsMixin.groups/user_permissions` 默认 `related_name='user_set'`，与 `auth.User` 冲突 | 在 `Account` 中覆盖两个 M2M，`related_name='r21_accounts'`（已写入架构决策） |
| 2 | 首次 `migrate` 因上项失败 | 同上 | 同上 |
| 3 | `test_password_lifecycle` 中 `services.AccountAuditLog` 引用 | 依赖 services 的再导出 | 断言直接通过 `services` 模块访问，已在实现侧保留导入 |

> 第 1 项是计划 G1 第 1 条要求验证的"不能假设"之处，属有价值发现。

## 4. 未运行 / 未覆盖（如实）

| 项 | 状态 | 原因 |
|---|---|---|
| 多浏览器（Firefox/WebKit） | NOT RUN | 仅安装 chromium |
| 移动端视口 | NOT RUN | 仅 1280×860 |
| 高并发双写压测 | NOT RUN | 无基准，不臆造结论 |
| `app01` 现有视图接入 RBAC | NOT DONE | 正式路径未切换 |
| 正式库回填/读切换 | NOT DONE | 需单独授权 |
