# S08 备份与恢复（验收报告）

- 实现：`scripts/pmr_upgrade_restore.py`
- 回归：`smass_operations/tests/test_pmr_pm5_upgrade_restore.py`（13 例）
- 关联：`docs/SMASS_PMR_Upgrade_Restore_Drill.md`（PM5 设计说明）

## 1. 验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| 合成全量数据 + schema 双指纹 | PASS | `restore.schema_fp_equal`、`restore.data_fp_equal` |
| 迁移元数据与账号/权限关系一致性 | PASS | `account_state.checks` 全 true |
| 灾难恢复演练实测 | PASS | 主演练 `exit=0`，真实 dump → import → 指纹比对 |
| MySQL DDL 非事务性风险记录 | PASS | 本文 §5 |

## 2. 真实演练流程

```bash
python scripts/pmr_upgrade_restore.py --json
```

实测（合成库 `smass_pmr_1k_20261031`，26 表 → 72 表）：

| 步骤 | 结果 |
|---|---|
| 源快照（表数/行数/结构指纹/数据指纹） | OK |
| 带数据克隆（`mysqldump` 含数据） | 行数 1:1 |
| 应用 R10 迁移 | `migrate_exit=0` |
| 迁移后行数保持 | OK |
| 备份升级库并导入全新恢复库 | OK |
| 表数 / 行数 / 结构指纹 / 数据指纹 | 全部相等 |
| H2 索引在恢复库仍生效 | OK |
| 源库行数 + 结构指纹 + 数据指纹 | 三项 unchanged |

## 3. 账号状态与权限关系校验（本轮新增）

新增 `_verify_account_state(source, upgrade, restore)`，在恢复后逐项比较：

| 检查 | 方法 | 结果 |
|---|---|---|
| `app01_admin/teacher/student` | 按 `ORDER BY id` 对 `(id,name,password,…)` 做 SHA-256，比较源库与恢复库 | 一致 |
| `django_migrations` | 对 `(app,name)` 排序摘要，比较升级库与恢复库 | 一致 |
| `auth_group` / `auth_permission` | 行数比较 | 一致 |
| `auth_user_groups` / `r21_account_accountrole` | 行数比较 | 一致 |
| `r21_account_account` | 行数比较（本演练不跑行迁移，预期 0） | 一致 |

这意味着恢复的不只是"表还在"，而是**账号状态、迁移记录、权限关系**都可核对。

## 4. 登录验证的诚实结论

PM5 不跑行迁移，`r21_account_account` 为空，登录验证针对旧表哈希。

当前环境**未注入** `SMASS_LEGACY_MD5_SECRET_KEY`，因此：

| 指标 | 实测 |
|---|---|
| `legacy_correct_accepted` | 0（正确密码也被拒绝） |
| `legacy_wrong_rejected` | 4/4 |
| `secret_injected` | false |
| 结论 | 这是 S01 的**安全默认生效**，不是恢复失败 |

本轮修正了演练脚本的判定逻辑：未注入密钥时，要求"正确密码也被拒绝"
才算通过；只有显式注入演练密钥时，才要求正确密码通过。
**没有为了让数字好看而注入真实历史密钥。**

## 5. 故障注入

三个注入点均以 `exit=0` 结束，源库三项指纹 unchanged：

| 注入点 | 时机 | 结果 |
|---|---|---|
| `before_migrate` | 克隆后、迁移前 | PASS |
| `during_backfill` | 迁移后插入半成品进度标记 | PASS |
| `after_index` | 迁移后、索引已建 | PASS |

## 6. 已知风险

| 风险 | 说明 | 处置 |
|---|---|---|
| MySQL DDL 非事务性 | 迁移中途失败无法按事务回滚 | 依赖备份 + 重建；演练已覆盖 |
| 进程被 kill 后自动恢复 | 未实现外部进程管理 | 记录为未覆盖，不声称支持 |
| 真实 `smass` 库 | 禁止写入/复制 | 全部使用合成数据 |
| 备份文件本身 | 本轮备份只落在临时目录 | 生产需接入受控备份存储与保留策略 |
