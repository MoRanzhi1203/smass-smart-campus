# SMASS R10 运维手册（Operations Manual）

> 适用范围：隔离开发/测试/演练环境。**正式部署需单独授权**。

## 1. 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12.x | 使用 conda `smass` 环境，**不得用 base** |
| Django | 5.2.17 | |
| MySQL | 8.0.x | 需 `utf8` 或 `utf8mb4` |
| PyMySQL | >=1.1.2,<2 | metadata 为准，`__version__` 不可靠 |
| cryptography | >=41,<51 | MySQL 8 `caching_sha2_password` 必需 |
| Playwright | 1.64.1（可选） | Chromium/WebKit/Firefox |

## 2. 安装（全新隔离库）

```powershell
$env:SMASS_DB_PASSWORD='<root 口令>'
conda run -n smass python scripts\r10_install.py
```

脚本行为：
1. 创建 `smass_r10_install_<ts>`（**存在即拒绝，不覆盖**）；
2. `migrate` 应用全部迁移；
3. 校验 8 张关键表存在；
4. `makemigrations --check` 确认无 pending；
5. **不删库**（清理需另行批准）。

实测：72 表、0 缺失、迁移一致。

## 3. 升级与回滚

```powershell
conda run -n smass python scripts\r10_upgrade_drill.py
```

实测结果：

| 步骤 | 结果 |
|---|---|
| 安装 | 72 表 |
| 回滚 `smass_analytics` 到 zero | 66 表（6 张表消失） |
| 其他模块数据 | **存活** |
| 重新升级 | 72 表恢复 |
| 最终数据 | **存活** |

**结论**：模块级迁移可逆，且回滚不波及其他模块数据。

## 4. 日常健康检查

| 端点 | 用途 | 期望 |
|---|---|---|
| `/r9/health/` | liveness（不查库） | 200 `{"status":"alive"}` |
| `/r9/ready/` | readiness（DB + 迁移） | 200；异常时 503 |
| `/r9/metrics/` | P50/P95/P99 + 错误率 | 200 |
| `/r9/alerts/` | 告警规则评估（不落库） | 200 |

## 5. 统一入口

`/r10/` 提供导航：组织与档案 / 教学管理 / 审批流程 / 统计看板 / API 文档 / 运维。
移动端（≤600px）导航自动堆叠；未登录也能访问该页（便于排障）。

## 6. 配置注册表

| 配置 | 位置 | 说明 |
|---|---|---|
| 数据库 | `smass/settings*.py` | 每个 R 阶段一套隔离 settings |
| 身份模式 | `R22_FLAGS.identity_mode` | `off`/`account`/`dual` |
| 登录限速 | `R21_LOGIN_RATE_LIMIT` | 窗口/阈值可调 |
| 小样本阈值 | `MetricDefinition.definition.min_group` | 默认 5 |
| API 限流 | `ServiceAccount.rate_limit_per_minute` | 默认 60 |
| 告警阈值 | `AlertRule` 表 | 可在线调整 |

## 7. 安全基线

| 项 | 状态 |
|---|---|
| 密码存储 | Django PBKDF2 |
| 服务令牌 | 仅存 SHA-256 摘要 |
| 审计 | `AccountAuditEvent`（批次可追溯） |
| 权限 | RBAC + 组织 scope + 字段级，默认拒绝 |
| 秘密扫描 | `scripts/r9_secret_scan.py`（0 issues） |
| 依赖审计 | `pip-audit`（0 漏洞） |

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `OperationalError:1040` | MySQL 连接数耗尽 | 检查 `Threads_connected`；长事务错峰；勿擅自改全局配置 |
| `caching_sha2_password` 认证失败 | 缺 `cryptography` | `pip install -r requirements.txt` |
| readiness 503 | 迁移 pending 或 DB 不可用 | 看 `/r9/ready/` 的 `checks[].detail` |
| 缓存条件约束未生效 | MySQL 不支持条件唯一索引 | 已知限制，靠服务层保证（见 §9） |
| WebKit 测试偶发 500 | LiveServer 连接复用竞态 | 测试层已加一次重试；非产品缺陷 |

## 9. 已知限制

1. **MySQL 不支持条件唯一索引**（`models.W036`）：
   `r21_account.AccountRole` 的 `r21_uniq_active_role` 与
   `smass_workflow.ApprovalTask` 的 `r6_uniq_open_task` **DB 约束未创建**，
   仅由服务层逻辑保证。并发下有理论窗口。
2. API 限流为**进程内**滑动窗口；多进程部署需换共享存储。
3. 服务账号默认**空 scope**，且 `read:students` 不等于全校可见
   （需 `admin:students`）。
4. 备份演练的 RTO（14.06s / 72 表）是**技术实测值**，非生产承诺。

## 10. 版本兼容矩阵

| 模块 | 依赖 | 迁移数 |
|---|---|---|
| `smass_organization` | `r21_account` | 1 |
| `smass_academic` | `r21_account`, `smass_organization` | 1 |
| `smass_workflow` | `r21_account` | 2 |
| `smass_analytics` | `smass_organization`, `smass_academic` | 1 |
| `smass_api` | 全部业务模块 | 1 |
| `smass_operations` | 无 | 1 |

## 11. 不做的事

- 不自动写入正式 `smass`；
- 不切换正式认证入口 / `AUTH_USER_MODEL`；
- 不删除既有库与真实数据；
- 不修改 MySQL 全局配置；
- 不推送远程；
- 不做生产部署。
