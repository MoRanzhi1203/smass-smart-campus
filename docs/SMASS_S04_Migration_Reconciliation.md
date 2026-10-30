# S04 数据迁移严格对账（验收报告）

- 实现：`scripts/pmr_migrate_rows.py`
- 回归：`smass_operations/tests/test_s04_migration_partition.py`（3 例，实际执行通过）
- 历史实现说明：`docs/SMASS_PMR_Row_Migration_and_Reconciliation.md`

## 1. 验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| 源行 100% 分区无歧义遗漏 | PASS | `reconciliation.partition.checks` 全 true |
| `strict_ok` 与 `lossless_ok` 区分 | PASS | 报告同时输出两个布尔值与 `overall_ok` |
| 隔离队列持久化与受控重放 | PASS | `pmr_rejected_queue` + `--replay` |
| 组织层级、重复 ID、字段截断、遗留哈希对账 | PASS | 测试覆盖孤儿专业/班级、超长名称、畸形哈希 |
| 合成 fixture 证据 | PASS | 测试自建 `smass_pmr_s04_*` 源库，运行后清理 |

## 2. 实现要点

### 2.1 分区语义

每个源行必须落入以下**恰好一个**分区：

| 分区 | 含义 | 落库位置 |
|---|---|---|
| mapped | 已建立目标映射 | `pmr_legacy_map` |
| isolated | 无法自动处理（缺父级等） | `pmr_rejected_queue.status='isolated'` |
| conflict | 冲突（保留首条） | `pmr_rejected_queue.status='conflict'` |
| truncated | 已迁移但字段被截断 | `pmr_rejected_queue.status='truncated'` |
| password_reset_required | 账号已建、哈希不可用 | `pmr_rejected_queue.status='password_reset_required'` |

`lossless_ok` 只检查 `mapped + isolated + conflict == source`，因此
"行被静默丢掉"会直接失败；`strict_ok` 检查结构、层级、哈希占位数量等。

### 2.2 隔离队列

```sql
CREATE TABLE pmr_rejected_queue (
  batch_id, source_table, source_id, reason, payload,
  status, attempts, created_at, resolved_at,
  UNIQUE KEY uq_rejected_source (batch_id, source_table, source_id, status)
)
```

- 写入使用 `INSERT ... ON DUPLICATE KEY UPDATE`，重复运行不膨胀；
- `payload` 只记录定位字段（名称/引用 ID），**不记录密码哈希**；
- 每次拒绝都可追溯到源表与源 ID。

### 2.3 受控重放

```bash
python scripts/pmr_migrate_rows.py --source <src> --target <tgt> \
  --batch-id <id> --replay
```

重放只重新执行**幂等迁移**，然后逐条检查隔离行是否已产生映射：

- 已产生映射 → `status='resolved'`、写 `resolved_at`；
- 仍缺父级 → `attempts+1`，保持在队列中，**不猜测父级**。

### 2.4 遗留哈希

畸形哈希仍建账号，但密码置为 `!<random>`，并进入
`password_reset_required` 队列；对账要求占位密码数量等于源中不可用哈希行数。

## 3. 实测结果

测试自建源库（6 张旧表、含 2 个孤儿引用、1 个超长班级名、1 个畸形哈希），
首次迁移后：

| 指标 | 值 |
|---|---|
| 源行总数（6 表） | 11 人 + 组织 |
| 隔离行 | major 1、classes 1、student_record 1 |
| 截断记录 | ≥ 1 |
| 分区检查 | 7/7 true |
| 重放后 remaining | 0 |
| 重放后分区检查 | 7/7 true |
| 重跑 skipped | ≥ 1（无重复插入） |

命令：

```bash
python manage.py test smass_operations.tests.test_s04_migration_partition \
  --settings=smass.settings_r10
```

结果：`Ran 3 tests ... OK`。

## 4. 修复的真实缺陷

`main()` 原先使用 `os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')`。
当测试/CI 已设置 `smass.settings_r10` 时，ORM 会连到 `smass_r10_release`，
而原生连接写目标库，导致"映射在目标库、账号在错误库"。已改为**强制覆盖**，
并在测试中验证目标库内账号、迁移记录与队列一致。

## 5. 边界

- 只使用合成数据；未读取、未写入正式 `smass` 库。
- 不替学校猜测专业/班级归属；无法确定的行只隔离，不自动挂接。
