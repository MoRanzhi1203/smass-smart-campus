# SMASS PMR Upgrade Restore Drill（PM5）

- 脚本：`scripts/pmr_upgrade_restore.py`
- 测试：`smass_operations/tests/test_pmr_pm5_upgrade_restore.py`（13 例，**13/13 PASS**）
- 与 H5 的区别：H5 只复制**结构**；PM5 复制**结构与数据**

## 1. 主流程结果（tiny 与 1k 均 exit=0）

| 步骤 | tiny | 1k |
|---|---|---|
| 源快照（表数/行数/双指纹） | ✓ | ✓ |
| 带数据克隆（行数 1:1） | ✓ | ✓ |
| 应用 R10 迁移（26 → 72 表） | ✓ | ✓ |
| 迁移后行数保持 | ✓ | ✓ |
| 备份 + 恢复 | ✓ | ✓ |
| 结构指纹一致 | ✓ | ✓ |
| 数据指纹一致 | ✓ | ✓ |
| H2 索引恢复后仍生效（4 行） | ✓ | ✓ |
| **抽样登录验证** | 4/4 | 4/4 |
| 源库未变（行数+结构+数据指纹） | ✓ | ✓ |

## 2. 关键实现细节

### 2.1 为什么必须复制 `django_migrations` 数据

继承 H5 的发现（PMD/H5 HD-009）：`mysqldump --no-data` 只复制结构，
`django_migrations` 表存在但**记录为空**，Django 会重跑初始迁移并撞表。

PM5 因为**带数据** dump（不加 `--no-data`），迁移记录天然被复制，
所以没有触发这个问题——但脚本仍单独校验了 `django_migrations` 的行数。

### 2.2 双重指纹

| 指纹 | 覆盖 | 用途 |
|---|---|---|
| `schema_fingerprint` | `information_schema.COLUMNS`（表/列/类型/可空/键/extra） | 结构是否一致 |
| `data_fingerprint` | 逐表行内容（排序后 join，再 sha256） | 数据是否一致 |

**两者都必须相等**才算恢复成功。只有结构指纹会漏掉"行丢了但表还在"的情况。

单测验证了：**插入一行后 data 指纹必须变化**（否则指纹无意义）。

### 2.3 登录验证为什么验 legacy 侧

PM5 只做**结构升级**（建 72 表 + 迁 12 条迁移），**不跑行迁移**，
所以 `r21_account_account` 是空的。

因此验证的是：升级/恢复后，`app01_*` 里的旧哈希能否被
`verify_password` 正确消费——这正是"升级后用户能否登录"的直接证据。

实测（1k）：

```
legacy_correct_accepted  = 4   # 4 个样本正确密码全部通过
legacy_wrong_rejected    = 4   # 4 个样本错密码全部拒绝
legacy_upgraded_on_success = 4 # 4 个样本命中后升级为 PBKDF2
```

## 3. 三个故障注入点

| 注入点 | 时机 | 结果 |
|---|---|---|
| `before_migrate` | 克隆完成后、迁移前 | exit=0，源库三项指纹 unchanged |
| `during_backfill` | 迁移后、插入半成品进度标记 | exit=0，业务行数仍完整，源库 unchanged |
| `after_index` | 迁移后、确认 H2 索引已建 | exit=0，索引 4 行存在，源库 unchanged |

三者都以 `Exit 0` 结束，且 `recovery` 段三项全为 `true`：

```json
"recovery": {
  "counts_unchanged": true,
  "schema_fp_unchanged": true,
  "data_fp_unchanged": true,
  "ok": true
}
```

**注意**：故障注入验证的是"**注入点之前的步骤没有破坏源库**"，
以及"升级后的业务数据仍完整"。它不是"进程被 kill 后自动恢复"的测试——
后者需要外部进程管理，本轮未做（见 §6）。

## 4. 本轮修掉的两个真 bug

**Bug 1：登录抽样的 index 用错**

首版 `plain_for(table, idx, source_id)` 用 `enumerate()` 的位置当 index。
但 SQL 里有 `WHERE LENGTH(password) = 32` 过滤，**过滤后的位置 ≠ 原始序号**。

1k 规模暴露：`legacy_correct_accepted = 1`（4 个样本只有 1 个对）。

修复：从 **id** 反推 index：

```python
digits = ''.join(ch for ch in str(source_id) if ch.isdigit())
index = int(digits)
```

修后 tiny 与 1k 都是 4/4。

**Bug 2：`settings_pmr` 只放行 target 前缀**

恢复库叫 `smass_pmr_restore_*`，被 settings 拒绝。
放宽为 `target_` / `upg_` / `restore_` 三类，仍禁止正式 `smass`。

## 5. 安全边界

| 要求 | 证据 |
|---|---|
| 源库只读 | 每次演练后比对行数 + 结构指纹 + 数据指纹，三项 unchanged |
| 无 PII | 源是 PM2 的合成库（`SYNTH%` 证件号 / `000%` 手机号） |
| 不覆盖已有库 | 建库前检查 `db_exists`，存在即拒绝 |
| 不删库 | 脚本无 DROP DATABASE |
| 不改 MySQL 全局 | 只设会话级隔离级别（settings_pmr） |

## 6. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实 `smass` 数据升级 | **BLOCKED_EXTERNAL_AUTH** | 禁止写正式库、禁止复制真实 PII |
| 进程被 kill 后的自动恢复 | **NOT RUN** | 需要外部进程管理；本轮只做"注入点后状态校验" |
| 10k 数据规模的升级耗时 | **NOT RUN** | 留到 PM6 与性能同测 |
| 跨 MySQL 版本升级 | **NOT RUN** | 仅本机 8.0.18 |
| 部分迁移失败后的事务回滚粒度 | **PARTIAL** | MySQL DDL 不支持事务回滚；依赖备份恢复 |

## 7. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 从合成旧库升级（含行） | §1 §2 |
| 复制迁移记录 | §2.1 |
| 行级规范摘要 + FK + 登录验证 | §2.2 §2.3 |
| 备份/恢复正常行数与关系 | §1 |
| 注入崩溃点（迁移前/回填中/索引后） | §3 |
| 恢复后 H2 索引仍生效 | §1（4 行） |
| 源库零写入 | §5 |
