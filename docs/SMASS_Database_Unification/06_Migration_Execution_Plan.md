# 06 迁移执行计划

> 范围：从正式库 `smass`（只读）到统一验证库 `smass_unified_verify` 的
> **可复现演练**，以及未来获得授权后的正式切换路径。
> 本轮不执行正式切换、不删除任何数据。

---

## 1. 环境与前置条件

| 项 | 要求 | 本轮状态 |
|---|---|---|
| Git 工作区 | 干净、基线 SHA 固定 | `f6c5b52`（本轮提交后） |
| 正式库 | 只读连接、只读事务、指纹基线 | `940a687d…`（迁移算法）/ `b914b39c…`（db_fingerprint） |
| 产品库 | 不动（仅只读检查） | `smass_product_dev` |
| 验证库 | 可随时重建 | `smass_unified_verify` |
| 数据所有者授权 | 正式迁移/切换必需 | **未取得**（本轮仅演练） |
| 加密备份 | 正式库独立加密备份 | **未满足**（见 10） |
| 舍弃清单审批 | `position/teacherposition` 等 | 未审批 |

---

## 2. 演练命令序列

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

# 1) 安全基线
git rev-parse HEAD
& $py scripts\db_fingerprint.py --out .local\evidence\unify\formal_fingerprint_before.json

# 2) 重建验证库 + 完整迁移
& $py scripts\db_unify.py init --json .local\evidence\unify\init.json

# 3) 基础配置与合成数据（幂等）
& $py scripts\db_unify.py seed --json .local\evidence\unify\seed.json

# 4) 结构/约束/外键/唯一性校验
& $py scripts\db_unify.py verify --json .local\evidence\unify\verify.json

# 5) 旧数据迁移（源库只读）
& $py scripts\legacy_migration.py --settings=smass.settings_unified_verify `
    --apply --json .local\evidence\unify\migration_apply.json

# 6) 对账
& $py scripts\db_unify_reconcile.py --json .local\evidence\unify\reconcile.json

# 7) 断库运行（临时重命名旧表，finally 恢复）
& $py scripts\db_unify_detached_test.py --json .local\evidence\unify\detached.json

# 8) 回滚 → 再迁移 → 再校验
& $py scripts\legacy_migration.py --settings=smass.settings_unified_verify --rollback
& $py scripts\legacy_migration.py --settings=smass.settings_unified_verify --apply
& $py scripts\legacy_migration.py --settings=smass.settings_unified_verify --verify

# 9) 全量回归 + 正式库指纹 + 准入
& $py scripts\r10_full_regression.py --json
& $py scripts\db_fingerprint.py --out .local\evidence\unify\formal_fingerprint_after.json
& $py scripts\repo_admission_check.py
```

---

## 3. 执行顺序与依赖

| 步骤 | 依赖 | 失败处理 |
|---|---|---|
| 指纹基线 | — | 失败则中止（无法证明只读） |
| `init` | 库前缀校验 | 重建可重试；不触碰其它库 |
| `seed` | 迁移完成 | 幂等，可重复 |
| `verify` | seed | 失败定位到具体约束/表 |
| 迁移 | 源库可读 + 目标空/半空 | 幂等（`LegacyAccountLink` 锚点） |
| 对账 | 迁移完成 | 差异即失败，人工确认 |
| 断库 | 验证库 | `finally` 恢复表名；异常也会恢复 |
| 回滚重迁 | 迁移完成 | 只删本批次无引用对象 |
| 回归 | 代码/配置 | 失败即阻断 |
| 指纹复核 | 回归后 | 必须与基线一致 |

---

## 4. 幂等与失败恢复

| 操作 | 幂等机制 |
|---|---|
| 建库/迁移 | `DROP/CREATE IF EXISTS` + Django `migrate` |
| seed | `update_or_create` + `get_or_create` |
| 账号迁移 | `LegacyAccountLink(source_table, source_pk)` 唯一锚点 |
| 组织 | 编码锚点 + 同名复用 |
| 学籍 | `student_no` 唯一 + `update_or_create` |
| 回滚 | manifest 记录本批次对象，仅删无引用项 |
| 断库测试 | `RENAME` 后 `finally` 恢复 |

**中断恢复**：迁移中断后重跑 `--apply`，已建 link 跳过，未完成项继续；
不会产生重复账号（实测首次失败续跑成功，`merged` 计数增加、账号不重复）。

---

## 5. 未来正式切换路径（需授权，本轮不执行）

```
① 数据所有者书面授权
② 正式库独立加密备份 + 恢复验证（RPO/RTO）
③ 新建生产库（新模型）→ migrate → seed 基础字典
④ 只读迁移 → 对账（七类 + 关键字段）
⑤ 产品配置指向新库，旧库只读并行观察（1–2 周）
⑥ 三端回归 + 业务验收
⑦ 停用旧库写入，保留只读归档
⑧ 满足保留期后，独立高风险审批 → 物理删除（不在本方案内）
```

**切换回滚**：产品配置切回旧库（旧库保持只读未删），
新库保留；数据以切换时点为准，期间新写入需回放（切换窗口内冻结写入）。

---

## 6. 门禁（任一失败即阻断）

1. 正式库指纹前后一致；
2. 验证库 `verify` PASS；
3. 迁移七类统计无 `rejected/unresolved > 0`（本轮 unresolved=0；
   `app01_teacherposition` 是表级未解决，未自动迁移）；
4. 对账 PASS；
5. 断库测试 PASS；
6. 回滚重迁 PASS；
7. 产品层 40 例 + 全量回归 PASS；
8. Git 准入 PASS；
9. 无运行时旧库依赖（扫描 0）。

---

## 7. 本轮执行结果

| 步骤 | 结果 |
|---|---|
| 验证库 init | PASS（127 表） |
| seed | PASS |
| verify | PASS |
| 迁移 | PASS（6 账号/3 学籍/12 单元/4 关系） |
| 对账 | PASS |
| 断库 | PASS（13 页 200/302） |
| 回滚重迁 | PASS |
| 全量回归 | 见 `09_Test_and_Rollback_Report.md` |
| 指纹 | 未变 |
| 准入 | PASS |
