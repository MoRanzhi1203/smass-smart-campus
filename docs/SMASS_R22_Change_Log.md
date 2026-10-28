# SMASS R2.2 G2–G4 变更清单（Change Log）

- 分支：`feat/smass-r22-account-cutover`
- 基线：`08d9b57`（R2.2 G0–G1）
- 范围：仅 G2–G4，隔离开发；G5–G8 未开始

## 1. 新增代码

| 文件 | 作用 |
|---|---|
| `r22_account/__init__.py` / `apps.py` | 隔离 app（仅 `settings_r22` 加载） |
| `r22_account/conf.py` | 特性开关（identity_mode / route_policy / audit / dry_run） |
| `r22_account/identity.py` | 五类身份解析 + `LegacyAccountLink` 权威判定 + 拒绝降级 |
| `r22_account/middleware.py` | `IdentityMiddleware`（`request.account` 契约）+ `RoutePolicyMiddleware` |
| `r22_account/audit.py` | 审计服务（事务语义、脱敏、actor 语义、`business_with_audit`） |
| `r22_account/models.py` | `AccountAuditEvent`（与 `django_admin_log` 完全分离） |
| `r22_account/views.py` | 身份/审计/legacy 探针 |
| `r22_account/migrations/0001_initial.py` | `AccountAuditEvent` |
| `r22_account/tests/`（5 文件） | 39 例 |
| `smass/settings_r22.py` | 隔离配置（库 `smass_r22_proto`） |
| `smass/urls_r22.py` | 隔离路由 |

## 2. 未修改（重要）

| 项 | 说明 |
|---|---|
| `app01/*` | **零改动**（10 处 `session['info']` 全部保持原样） |
| `smass/settings.py` | 未改；不加载 `r22_account` |
| `AUTH_USER_MODEL` | 未改（仍 `auth.User`） |
| `r21_account/*` | 未改（R2.1 原型完整保留） |
| 既有迁移 | 未重写 |
| `smass` 库 | 未写入 |
| `smass_r22_b_switch` | 仅作 EVIDENCE_ONLY，未使用 |

## 3. 行为变化（仅 `settings_r22` 环境）

| 场景 | 行为 |
|---|---|
| `request.account` | 新增契约：`Account` 或 `None`，懒解析 + 请求级缓存 |
| `request.legacy_identity` | 新增：规范化后的旧身份 |
| 路由准入 | 由 `RoutePolicyMiddleware` 按"路由 × 身份类型"判定 |
| 审计 | 写 `AccountAuditEvent`，不写 `django_admin_log` |
| 停用账号 + 旧 session | 判为 `conflict` 并拒绝（不降级） |

> 正式 `smass` 环境行为**完全没有变化**。

## 4. 测试

| 套件 | 用例 | 结果 |
|---|---|---|
| `r22_account`（G2–G4） | 39 | **PASS** |
| `r21_account`（回归） | 72 | PASS |
| `app01`（回归，正式配置） | 114 | PASS |
| `tests_e2e`（回归，正式配置） | 16 | PASS |
| 合计 | **241** | 全绿 |

## 5. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 停用账号借旧 session 越权 | 判 conflict 并拒绝（有测试） | — |
| 审计丢失 | 失败场景独立写入 | 关闭 `audit_enabled` |
| 审计写爆 `django_admin_log` | 完全不写该表（有反证测试） | — |
| 懒对象语义误解 | `_unwrap()` + `isinstance` 断言 | 改即时解析 |
| 正式系统受影响 | 不加载 app/中间件 | 无需回滚 |

**回滚命令**（隔离环境）：

```powershell
# 关闭身份兼容层（最小爆炸半径）
# 在 settings_r22.py 中把 R22_FLAGS['identity_mode'] 设为 'off'
# 或从 MIDDLEWARE 移除 r22_account.middleware.* 两项
```

## 6. 遗留（NOT DONE / NOT AUTHORIZED）

1. G5–G8 全部未开始（克隆回填演练、性能基线、浏览器 E2E、切换门禁）；
2. `app01` 视图接入 `request.account`；
3. 正式认证路径切换、`AUTH_USER_MODEL` 变更；
4. 审计查询界面与保留策略；
5. 冲突事件运营告警。

---

## 7. R2.2 G5 变更（隔离回填演练）

| 文件 | 变更 |
|---|---|
| `scripts/r22_g5_ro_user.py`（新） | 创建/验证**数据库级只读**账号（仅 SELECT；4 类写探测全部被拒） |
| `scripts/r22_g5_stage.py`（新） | 只读快照（mysqldump --single-transaction）+ 隔离 stage 库，拒绝覆盖既有库 |
| `scripts/r22_g5_drill.py`（新） | 差异注入检测、回滚范围验证、二次回填恢复 |
| `smass/settings_r22_g5.py`（新） | 演练配置（库必须命中 `smass_r22_g5_`） |
| `r22_account/tests/test_g5_backfill.py`（新） | 18 例：白名单/幂等/哈希/故障注入/回滚范围/差异检测 |
| `r21_account/.../backfill_accounts_r21.py` | 白名单扩展（`smass_r22_g5_`、`test_smass_`）；输出改走 `self.stdout` |
| `r21_account/.../verify_account_consistency.py` | 重写：`--json` / `--plan-only`、9 个差异码、修正误报、无 repair 选项 |

**环境变更**：安装 `cryptography 50.0.2`（MySQL 8 `caching_sha2_password` 认证所需）。
该依赖**尚未**写入 `requirements.txt`（见风险 R9）。

**新增数据库**：`smass_r22_g5_stage`（隔离演练库，本轮**未删除**）。
**新增数据库账号**：`smass_g5_ro`（仅 `SELECT ON smass.*`）。

**未修改**：`app01/*`、`smass/settings.py`、`AUTH_USER_MODEL`、既有迁移、R2.1 模型。
---

## 8. R2.2 G6–G8 变更（自主执行轮）

| 文件 | 变更 |
|---|---|
| `requirements.txt` | 新增 `cryptography>=41,<51`（运行依赖，修复 MySQL 8 caching_sha2 认证） |
| `scripts/r22_g6_bench.py`（新） | 合成数据基准：五类身份延迟/SQL、scoping、并发 1/10/50 |
| `smass/settings_r22_g6.py`（新） | G6 合成库配置（库名强制 `smass_r22_g6_`） |
| `r22_account/tests/test_g7_browser.py`（新） | 浏览器 E2E 8 例（三端×视口、强制改密、legacy 路由、停用、403） |
| `r22_account/middleware.py` | 修复 `_deny` 跳转到不存在的 `/login/`（改为 `/r21/login/`） |

**新增数据库**：`smass_r22_g6_synth`（1,146 合成账号，**未删除**）。

**未修改**：`app01/*`、`smass/settings.py`、`AUTH_USER_MODEL`、既有迁移、R2.1 模型。

**测试变化**：267（原 259 + G7 8）。r22_account 由 57 增至 65。