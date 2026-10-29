# SMASS R10 Existing DB Upgrade Drill（H5）

- 演练脚本：`scripts/r10_upgrade_clone_drill.py`
- 演练配置：`smass/settings_h5.py`（继承 `settings_r10`，仅放宽库名前缀）
- 源库：`smass`（**只读**，26 表）
- 结果：**全部步骤通过**

## 1. 结果总览

| 步骤 | 结果 | 关键数字 |
|---|---|---|
| 源库快照 | **PASS** | 26 表；Admin 1 · Student 3 · Teacher 2 |
| 只读账号写拒绝 | **PASS** | `smass_g5_ro` 写被拒 |
| schema-only 克隆 | **PASS** | 26 → 26 表 |
| **应用 R10 迁移** | **PASS** | 26 → **72 表**；迁移记录 22 → **34** |
| 关键表健在 | **PASS** | `auth_user` / `app01_admin` / `app01_student` / `app01_teacher` / `r21_account_account` / `r22_account_accountauditevent` 全在 |
| H2 唯一索引随迁移进入 | **PASS** | `uq_r21_active_role` / `uq_r6_open_task` 共 4 行 |
| 备份 + 恢复到新库 | **PASS** | 72 → 72 表 |
| 结构指纹比对 | **PASS** | `284c1c1d...` 两侧一致 |
| **源库未变** | **PASS** | 26 表、1-3-2、指纹不变 |

## 2. 关键发现：`django_migrations` 数据必须一并复制

第一次演练失败：

```
django.db.utils.OperationalError: (1050, "Table 'django_content_type' already exists")
```

`--fake-initial` 也失败：

```
django.db.utils.OperationalError: (1050, "Table 'app01_admin' already exists")
```

**根因**：`mysqldump --no-data` 只复制**结构**，`django_migrations` 表结构有了、
**记录是空的**。Django 因此认为"所有迁移都未应用"，尝试重跑
`contenttypes.0001_initial` 与 `app01.0001_initial`，撞上已存在的表。

**修复**：额外用 `mysqldump --no-create-info smass django_migrations`
复制那 22 行迁移记录（只含 app 名 + 迁移名 + 时间，**不含 PII**）。

**验证**：复制后 `migrate` 只执行 R10 新增的 12 条迁移，22 → 34。

**这是一个真实的升级陷阱**：任何"用 dump 复制现有 Django 库再做迁移"的流程，
如果只 dump 结构就会踩这个坑。已在决策日志 HD-009 记录。

## 3. 安全边界证据

| 要求 | 证据 |
|---|---|
| 源库只读 | 用 `smass_g5_ro` 尝试 `CREATE TEMPORARY TABLE` → 被拒 |
| 不复制真实行 | `--no-data`：克隆 26 表**零行**（只复制结构） |
| 不复制 PII | `django_migrations` 数据不含姓名/哈希 |
| 克隆库不覆盖 | 库名 `smass_h5_clone_<ts>`，创建前 `db_exists` 检查，存在即拒绝 |
| 源库未变 | 前后指纹 `284c1c1d9c1069445695f352406a66f9` 一致；26 表；1-3-2 |
| 不删库 | 脚本不删任何库；报告中明写"清理需另行批准" |

## 4. 范围限制（必须明说）

**本次证明的是"结构升级"，不是"数据迁移"。**

| 证明的 | 未证明的 |
|---|---|
| 26 表结构可被 R10 迁移链正确处理 | `app01_*` 里的真实行能否无损迁移到新模型 |
| 系统表（auth/django/app01）与 R10 新表共存 | 真实姓名/哈希的映射与校验 |
| H2 生成列索引随迁移正确创建 | 迁移过程中密码哈希的格式转换 |
| 备份/恢复完整 | 生产数据量下的迁移耗时与锁影响 |

**为什么不做数据迁移**：`smass` 的 `app01_admin/student/teacher` 含真实姓名与
密码哈希。把它们复制到克隆需要**单独的数据处理授权**，且会扩大 PII 暴露面。
计划明确要求"prefer synthetically populated schema-compatible clone"。

**因此**：数据迁移标 `NOT RUN`（需授权），不标 BLOCKED（技术路径已明确，
只差授权）。

## 5. 与计划的对应

| 计划要求 | 本演练 |
|---|---|
| 用只读源 + 验证写拒绝 | §3 |
| 唯一命名、不存在才建、拒绝覆盖 | 脚本 `db_exists` + `ALLOWED_PREFIXES` |
| 保护真实个人数据 | schema-only，零行复制 |
| 首取源库计数与指纹 | §1 |
| 应用真实迁移链 | 26 → 72 表，22 → 34 迁移 |
| 区分 `settings.py` 与 `settings_r10` | 用 `settings_h5`（继承 r10） |
| 校验用户映射/表/外键/关键查询 | 关键表存在性 + 指纹 |
| 备份恢复演练 | 72 → 72 + 指纹一致 |
| 不把 72 表当成默认期望 | 实测得到，非假设 |
| 源库未被修改 | 附录指纹对比 |

## 6. 产物位置

- `%TEMP%\smass_h5_drill\source_schema_<ts>.sql`（源结构 dump）
- `%TEMP%\smass_h5_drill\django_migrations_<ts>.sql`（22 行迁移记录）
- `%TEMP%\smass_h5_drill\clone_upgraded_<ts>.sql`（升级后克隆全量备份）
- 克隆库 `smass_h5_clone_<ts>`、恢复库 `smass_h5_restore_<ts>`（保留，不自动删除）

这些都在临时目录/隔离库中，**未进入 Git**。
