# SMASS R10 Release GO / NO-GO（H9）

- 基线：`488f6c5`
- 分支：`feat/smass-r4-r10-integrated-platform`
- 设置：`smass.settings_r10`（READ COMMITTED）
- 实测回归：**811 例全绿**（10 套件）

## 1. 最终判定

```
GO_RECOMMENDED        = YES（隔离环境发行候选）
PRODUCTION_DEPLOYMENT = NOT_AUTHORIZED
```

两者不同：**技术门禁通过 ≠ 生产上线许可**。
生产部署需要独立授权（见 §6）。

## 2. H0–H9 状态

| ID | 任务 | 状态 | 关键证据 |
|---|---|---|---|
| H0 | 基线审计与数据库边界 | TESTED | 60 路由、MIDDLEWARE 审计、发现 RedirectView 顶替 |
| H1 | 真实密码生命周期 | TESTED | 18 例；改密生效、校验完整、多会话失效 |
| H2 | MySQL 唯一约束 | TESTED | 10 例；DB 拒绝重复（1062）、4 线程并发只 1 个 active、迁移可逆 |
| H3 | WebKit 500 根因 | TESTED | 完整栈定位 `update_last_login`；READ COMMITTED 修复；2 例回归保护 |
| H4 | 可访问性 | TESTED | 15 例；skip link / h1 / aria 关联 / 200% / 强制颜色 |
| H5 | 26 表升级演练 | TESTED | 26→72 表、迁移 22→34、H2 索引 4 行、备份恢复指纹一致、源库未变 |
| H6 | 集成安全 | TESTED | 27 例；跨面一致、伪造不提权；**修 2 个跨 settings 回归** |
| H7 | 三浏览器 E2E | TESTED | Chromium 6/6、Firefox 10/10、WebKit 每类独立 4/4 + 并发 |
| H8 | 全量回归与打包 | TESTED | 811 例、check 0、pip-audit 0 漏洞、秘密扫描 PASS、源库未变 |
| H9 | 就绪评估 | TESTED | 本文件 |

**10/10 TESTED。**

## 3. 关键安全与数据完整性结论

| 项 | 结论 |
|---|---|
| 强制改密 | **真实生效**（此前被 RedirectView 完全禁用） |
| 唯一约束 | **数据库级生效**（生成列 + 唯一索引），不再只靠服务层 |
| 跨面一致性 | UI / CSV / R7 指标与服务层一致；API 服务账号默认空集 |
| 小样本抑制 | 对外输出被抑制，服务层内部可见 |
| 会话安全 | 改密后其他会话自动失效（Django `_auth_user_hash`） |
| 伪造请求 | 全部拒绝，数据未变 |
| 审计 | 授予/撤销可追溯，重复授予不产生第二行 |

## 4. 风险登记（复评）

| ID | 风险 | 等级 | 状态 | 影响面 |
|---|---|---|---|---|
| R-01 | MySQL 条件唯一约束 | ~~中~~ **已消除** | 生成列方案替代 | — |
| R-03 | 改密占位重定向 | ~~中~~ **已消除** | H1 修复 | — |
| R-15 | WebKit 同进程多类登录失败 | **低** | 未根治，可规避 | 仅测试环境 |
| R-16 | 真实行数据迁移未做 | **中** | NOT RUN（需 PII 授权） | 生产升级 |
| R-17 | 旧 MD5 哈希升级未验证 | **中** | NOT RUN（需真实样本） | 生产登录 |
| R-18 | 屏幕阅读器实机未测 | **中** | NOT RUN | 无障碍合规 |
| R-19 | axe 自动扫描未做 | **低** | NOT RUN（无离线包） | 无障碍 |
| R-20 | 真实 Windows 高对比主题未走查 | **低** | PARTIAL | 无障碍 |
| R-21 | 生产数据量压测未做 | **中** | NOT RUN | 性能 |
| R-22 | 多进程 API 并发未压测 | **低** | NOT RUN | 容量 |
| R-23 | MySQL 5.7 未验证 | **低** | NOT RUN | 兼容性 |
| R-24 | 业务政策缺失（BD-05/06/07/08） | **中** | BUSINESS_CONFIG_PENDING | 功能完整性 |
| R-25 | 管理员重置临时密码 UI 未做 | **低** | PARTIAL | 运维便利 |

**高危：0 项。**

## 5. 为什么 GO 是合理的

1. **两个 P0 已实修**：改密失效、唯一约束缺失——都有数据库级验证，不是"看起来很对"
2. **811 例全绿**，含真实浏览器提交与 DB 状态断言
3. **升级路径已实测**：26 表结构可升级到 72 表、可备份恢复、源库零写入
4. **跨 settings 回归已覆盖**，并因此发现 2 个只在 r10 暴露的缺陷
5. **依赖审计无漏洞**、秘密扫描 0 生产凭据
6. **所有未做项都如实记录**，没有用跳过冒充通过

## 6. 为什么生产部署仍是 NO-GO

| 阻断项 | 原因 |
|---|---|
| R-16 真实行迁移 | 未验证旧库真实数据能否无损迁移；需 PII 授权 |
| R-17 旧哈希升级 | `app01_*` 的密码格式未验证，升级后能否登录未知 |
| R-21 生产数据量压测 | 只有合成数据，锁与耗时未知 |
| R-24 业务政策 | BD-05/06/07/08 未输入，演示流程不能当生产规则 |
| 正式认证切换 | 未授权 |
| 备份/回滚生产拓扑 | 只在隔离库验证过 |

**结论**：技术上可上线试运行于隔离环境；生产上线需先解决 R-16/R-17/R-24 并取得授权。

## 7. 运维 runbook（给下一位操作者）

### 环境要求
- Python 3.12（conda `smass` 环境，**不用 base**）
- MySQL 8.0.x
- 依赖：`pip install -r requirements.txt`（含 `cryptography>=41,<51`）

### 关键配置
```python
# settings_r10
DATABASES['default']['OPTIONS']['init_command'] = (
    "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
```
**不要**改回 REPEATABLE READ——会导致 `update_last_login` 在并发下 500。

### 启动
```powershell
conda run -n smass python scripts/r10_demo_seed.py      # 合成演示数据
conda run -n smass python manage.py runserver 8000 --settings=smass.settings_r10
```

### 升级现有库
```powershell
conda run -n smass python scripts/r10_uniqueness_precheck.py    # 先查重复
conda run -n smass python scripts/r10_upgrade_clone_drill.py    # 克隆演练
```
**必须**同时 dump `django_migrations` 的数据，否则 1050 冲突（见 HD-009）。

### 回滚
- 迁移：`manage.py migrate r21_account 0001` + `migrate smass_workflow 0002`
- 数据库：用备份恢复；H5 已证明指纹一致

### 排障
| 现象 | 原因 | 处理 |
|---|---|---|
| 1040 Too many connections | 长事务占用 | 检查 `Threads_connected`；勿改全局 |
| `Save with update_fields` | 隔离级别被改回 REPEATABLE READ | 恢复 READ COMMITTED |
| `1050 Table already exists` | 升级时未复制迁移记录 | 补 dump `django_migrations` |
| WebKit 测试登录失败 | R-15 同进程累积 | 每类独立 `manage.py test` |

## 8. 最终证据

| 项 | 值 |
|---|---|
| 分支 | `feat/smass-r4-r10-integrated-platform` |
| 基线 SHA | `488f6c5` |
| 实测测试数 | **811**（基线 733，+78） |
| 套件数 | 10（0 失败） |
| 高危风险 | **0** |
| `smass` 数据库 | 26 表 / Admin 1 · Student 3 · Teacher 2（未变） |
| `AUTH_USER_MODEL` | 未改 |
| `app01` 代码 | 未改 |
| 迁移一致性 | formal / r10 / r21 均 No changes |
| 依赖审计 | 无已知漏洞 |
| 秘密扫描 | 0 生产凭据 |

## 9. 一句话结论

**两个 P0 缺陷（强制改密形同虚设、唯一约束从未存在）已实修并有数据库级证据；
811 例全绿；升级与恢复路径已实测。技术上可进入隔离环境试运行，
生产上线因数据迁移、旧哈希兼容与业务政策未决而保持 NO-GO。**
