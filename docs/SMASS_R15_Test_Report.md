# SMASS R1.5 测试报告（Test Report）

- 执行时间：2026-10-27
- 环境：Windows / conda env `smass`（Python 3.12.16）/ Django 5.2.13 / MySQL 8.0.18
- 测试库：`test_smass`（Django 自动创建与销毁，**不触碰开发库 `smass`**）

## 1. 结果总览

| 套件 | 命令 | 用例数 | 结果 | 耗时 |
|---|---|---|---|---|
| 应用回归 | `manage.py test app01` | **112** | **PASS 112/112** | 58.342s |
| 浏览器 E2E | `manage.py test tests_e2e` | **16** | **PASS 16/16** | 35.186s |
| 原型失败注入 | `python scripts/proto_failure_injection.py` | 9 项检查 | **PASS 9/9** | — |
| 原型一致性 | `python scripts/proto_verify.py` | 5 类校验 | **PASS** | — |
| 备份恢复演练 | `scripts\db_restore_drill.ps1` | 1 次演练 | **PASS**（26 表/24 FK/22 迁移/158 行一致） | — |
| 字符集转换演练 | `scripts\charset_drill.ps1` | 1 次演练 | **PASS**（26 表/24 FK 重建/4 字节字符） | — |

## 2. app01 套件构成

| 文件 | 用例 | 说明 |
|---|---|---|
| `test_auth.py` | 21 | 登录/密码完整性/改密/旧 MD5 兼容 |
| `test_authorization.py` | 17 | 匿名拦截/跨角色/CSRF/对象归属 |
| `test_crud_admin.py` | 24 | 9 模块列表搜索往返、串台、误删 |
| `test_imports.py` | 17 | 模板一致性、导入事务与回滚 |
| `test_compat_tools.py` | 8 | 兼容层与管理员 UI 入口 |
| `test_high_risk.py` | 22 | **本轮新增**：清表默认拒绝、purge_table 三重门禁、no-store、脱敏、MD5 向量 |
| `test_query_budget.py` | 3 | **本轮新增**：查询数基准与"N+1 不随行数增长" |
| **合计** | **112** | 基线 87 → 本轮 112（+25） |

## 3. 本轮新增用例覆盖点

| 计划要求 | 用例 | 结果 |
|---|---|---|
| B.2 清表默认拒绝 | `DisabledHttpClearTests`（3） | PASS |
| B.2 受控命令门禁 | `PurgeTableCommandTests`（5，含 DEBUG=False 拒绝） | PASS |
| B.3 CSRF/方法/跨角色 | 沿用 `test_authorization`（17） | PASS |
| B.7 一次性口令不缓存 | `SensitiveResponseHeaderTests`（3） | PASS |
| B.5 手机号脱敏 | `MaskPhoneFilterTests`（5）+ `StudentPhoneIsMaskedInTemplateTests`（1） | PASS |
| B.6 旧 MD5 向量 | `LegacyHashVectorTests`（4，用 hashlib 独立重算） | PASS |
| §7.4 查询数基准 | `QueryBudgetTests`（3） | PASS |

## 4. 本轮真实失败与修复记录

| # | 失败现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | `purge_table` 测试报 `DJANGO_DEBUG=False` | Django 测试运行器强制 `DEBUG=False`，触发命令的第三重门禁（设计正确） | 测试用 `override_settings(DEBUG=True)`；另补 `DEBUG=False` 必须 `--allow-non-debug` 的用例 |
| 2 | 恢复演练 `[WARN] drop failed` 且**演练库真的残留** | `DROP DATABASE \`name\`;` 在 `cmd /c` 下反引号异常；脚本用 cmd 退出码判定 | 去反引号 + 改查 `information_schema` 以事实判定；残留库已清理 |
| 3 | `Start-Process` 抛 `NO_PROXY/no_proxy` 重复键异常 | PowerShell 5.1 已知缺陷 | 备份/恢复/字符集脚本统一改 `cmd /c` 字节级重定向 |
| 4 | 字符集演练 `ERROR 3780 ... are incompatible` | 逐表 CONVERT 时 FK 两端字符集不一致 | 改为"预生成 ADD FK → DROP FK → CONVERT → 重建 FK"，24 个外键全部恢复 |
| 5 | E2E 全部 `AttributeError: no attribute 'admin'` | `StaticLiveServerTestCase`（TransactionTestCase）**不执行** `setUpTestData` | 夹具移入 `setUp` |
| 6 | E2E 全部 `SynchronousOnlyOperation` | Playwright 同步 API 建立事件循环，Django 判定为 async 上下文 | `DJANGO_ALLOW_ASYNC_UNSAFE=true`（**仅测试进程**，Django 官方逃生舱） |
| 7 | 3 个 E2E 模态框等待超时 | 后台用 Bootstrap **3**，显示态 class 是 `.in` 而非 `.show` | 改为 `wait_for_selector(..., state='visible')`，不依赖 BS 版本 |
| 8 | 导入 E2E `page.content` 导航竞态 | `form.submit()` 触发导航后立即取内容 | 用 `expect_navigation()` 包裹 |
| 9 | **查询数基准捕获真实 N+1** | 模板访问 `obj.classes.major.college`，视图 `select_related` 少了这一层 | 补 `classes__major__college`：列表查询数 **10 → 4**，行数增加后仍为 4 |

> 第 9 项说明：基准不是形式主义，它在建立过程中直接发现并量化了一个真实的 N+1。

## 5. 查询数基准（实测）

| 页面 | 修复前 | 修复后 | 上限 |
|---|---|---|---|
| `/admin/student/list/` | 10（且随行数增长到 19） | **4** | 8 |
| `/admin/teacher/list/` | — | 5 | 8 |
| `/admin/classes/list/` | — | 6 | 9 |
| `/admin/college/list/` | — | 3 | 6 |
| `/admin/student/detail/` | — | 2 | 5 |
| 学生列表搜索 | — | 4 | 6 |

行数从 6 增至 16 后，`/admin/student/list/` 查询数恒为 4。

## 6. 迁移测试

| 场景 | 命令 | 结果 |
|---|---|---|
| 从零迁移（每次测试自动执行） | `manage.py test app01` | 22 个迁移全部 `OK`，26 表 |
| 模型与迁移一致性 | `makemigrations --check --dry-run` | No changes detected |
| R1 最新迁移向前升级 | 开发库已在 0004 | `showmigrations` 全 `[X]` |
| 原型库独立迁移 | `migrate --settings=smass.settings_proto` | `proto_account.0001_initial` 等全部 OK |

> 本轮**未新增** `app01` 迁移（无 schema 变更）；原型新增迁移只存在于 `proto_account`，
> 由 `settings_proto` 加载，不影响正式链路。

## 7. 未运行 / 未覆盖（如实声明）

| 项 | 状态 | 原因 |
|---|---|---|
| 依赖漏洞扫描（`pip-audit`） | **NOT RUN** | 工具未安装；本轮未获授权安装第三方扫描器。已在安全报告列为待办 |
| 计划任务注册 | **待部署** | 创建系统计划任务需显式授权，未执行 |
| 首次登录强制改密的**三端 UI** | **NOT DONE** | 会与 R2.0 身份迁移冲突；按计划只在原型模型加 `must_change_password` 字段并完成设计 |
| 持久化登录限速的运行时逻辑 | **原型字段已建，逻辑未接** | 同上，属 R2.1 |
| 移动端/多浏览器视口 | **未测** | 仅 Chromium 桌面 1366×900 |
| 真实文件选择对话框 | **未测** | E2E 用 `DataTransfer` 注入文件，绕过原生对话框 |
| 性能压测（并发/大表） | **未测** | 无基准数据，未做无依据的"更快"结论 |

## 8. 复跑入口

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1     # app01 112 + check + 迁移一致性
conda run -n smass python manage.py test tests_e2e -v 1        # 浏览器 E2E 16
conda run -n smass python scripts\proto_verify.py              # 原型一致性
conda run -n smass python scripts\proto_failure_injection.py   # 原型失败注入
```
