# SMASS R2.2.1 变更清单（Change Log）

- 分支：`feat/smass-r221-release-readiness`
- 基线：`f9a99dd`

## 1. 新增文件

| 文件 | 作用 |
|---|---|
| `smass/settings_r22_g221.py` | 万级规模配置（库名强制 `smass_r22_g221_`） |
| `scripts/r221_scale.py` | 10,000 合成账号全流程（生成/回填/幂等/一致性/回滚/二次回填/批次审计） |
| `scripts/r221_conn_capacity.py` | 并发容量边界测量（5–50 worker，含服务端状态快照） |
| `r22_account/tests/test_c_browser_matrix.py` | 跨引擎浏览器矩阵（5 例，`R221_BROWSER` 选择引擎） |

## 2. 修改文件

| 文件 | 变更 |
|---|---|
| `r21_account/management/commands/backfill_accounts_r21.py` | 白名单扩展 `smass_r22_g221_` |
| `r21_account/management/commands/verify_account_consistency.py` | 同上 |

## 3. 未修改（保持隔离）

| 项 | 说明 |
|---|---|
| `app01/*` | 零改动 |
| `smass/settings.py` | 未改 |
| `AUTH_USER_MODEL` | 未改（仍 `auth.User`） |
| 既有迁移 | 未重写 |
| 正式认证入口 | 未切换 |

## 4. 环境变更

| 项 | 变更 |
|---|---|
| Playwright browsers | 新增 **WebKit 27.2（webkit-2370）**、**Firefox 157.0（firefox-1555）** |
| MySQL 全局配置 | **未改** |

## 5. 新增数据库

| 库 | 内容 | 状态 |
|---|---|---|
| `smass_r22_g221_scale` | 10,000 全合成学生 + 回填产物 | 保留（**未删除**） |

## 6. 测试变化

| 套件 | 之前 | 现在 |
|---|---|---|
| r22_account | 89 | **94**（+5 browser matrix） |
| r21_account | 72 | 72 |
| app01 | 114 | 114 |
| tests_e2e | 16 | 16 |
| **合计** | 291 | **296** |

浏览器矩阵另在 WebKit / Firefox 各跑 5 例（通过环境变量切换，不重复计入套件）。

## 7. 本轮修复的缺陷

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | 规模脚本未接批次审计 | 改用 `batch_audit.run_backfill/run_rollback` |
| 2 | 容量脚本 `student_no` 截断冲突（假 `IntegrityError`） | 独立唯一值 |
| 3 | 容量脚本错误分类缺失 | 记录 `errno` |
| 4 | WebKit 下 LiveServer 连接竞态导致随机 500 | 登录步骤加一次请求级重试（两次失败仍 FAIL） |
| 5 | 容量脚本保守阈值把 30–50 worker 误标 BLOCKED | 阈值调到 50（仍远低于饱和） |

## 8. 结论修正（对上一轮）

| 项 | 上一轮结论 | 本轮修正 |
|---|---|---|
| 并发上限 | 20（保守） | 50 worker 短事务零错误；瓶颈是长事务 |
| GO 条件 | 需扩容 | 改为"监控连接数" |
| 跨浏览器 | 2/3 | **3/3** |
