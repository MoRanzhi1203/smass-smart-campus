# SMASS R10 Uniqueness Enforcement Report（H2）

- 测试：`smass_operations/tests/test_r10_h2_uniqueness.py`（10 例）
- 预检：`scripts/r10_uniqueness_precheck.py`
- 结果：**10/10 PASS**；迁移可逆实测通过

## 1. 问题实证（不是推测）

Django 在 `AccountRole` 与 `ApprovalTask` 上声明了条件唯一约束：

```python
UniqueConstraint(fields=['account', 'role'],
                 condition=Q(revoked_at__isnull=True), name='r21_uniq_active_role')
UniqueConstraint(fields=['instance', 'node'],
                 condition=Q(status='open'), name='r6_uniq_open_task')
```

**MySQL 8.0.18 不支持部分/条件索引**（Django 报 `models.W036`）。
实测 `SHOW INDEX`：

```
r21_account_accountrole:
  PRIMARY
  r21_account_account_a5aa86_idx (account_id, revoked_at)  non_unique=1
  ← 没有 r21_uniq_active_role

smass_workflow_approvaltask:
  PRIMARY
  ..._instance_id_fk / ..._node_id_fk / assignee+status   non_unique=1
  ← 没有 r6_uniq_open_task
```

**结论**：约束从未在数据库层存在，只靠服务层"先查再插"，
并发下存在理论窗口。

## 2. 方案：生成列 + 唯一索引

利用「MySQL 唯一索引中 NULL 互不相等」的语义：

### AccountRole

```sql
ALTER TABLE r21_account_accountrole
  ADD COLUMN active_account_id BIGINT
    GENERATED ALWAYS AS (IF(revoked_at IS NULL, account_id, NULL)) VIRTUAL,
  ADD UNIQUE KEY uq_r21_active_role (role, active_account_id);
```

| 行状态 | `active_account_id` | 索引行为 |
|---|---|---|
| active | `account_id` | 同 role 同 account 冲突 ✓ |
| 已撤销 | `NULL` | 永不冲突，历史可累积 ✓ |

### ApprovalTask

```sql
ALTER TABLE smass_workflow_approvaltask
  ADD COLUMN open_instance_id BIGINT
    GENERATED ALWAYS AS (IF(status='open', instance_id, NULL)) VIRTUAL,
  ADD COLUMN open_node_id BIGINT
    GENERATED ALWAYS AS (IF(status='open', node_id, NULL)) VIRTUAL,
  ADD UNIQUE KEY uq_r6_open_task (open_instance_id, open_node_id);
```

## 3. 迁移实现

两个迁移均使用 `SeparateDatabaseAndState`：

```python
SeparateDatabaseAndState(
    state_operations=[RemoveConstraint(...)],      # 移除 MySQL 建不出的条件约束
    database_operations=[RunSQL(FORWARD, REVERSE)],# 真正建生成列 + 唯一索引
)
```

好处：
- Django state 不再持有那条假约束 → **`models.W036` 消失**
- `makemigrations --check` 在 formal / r10 / r21 三套 settings 下均 `No changes`
- `reverse_sql` 完整回滚

## 4. 数据库级验证（真实，不是 mock）

### 4.1 索引存在

```python
information_schema.STATISTICS
  uq_r21_active_role  NON_UNIQUE=0  ✓
  uq_r6_open_task     NON_UNIQUE=0  ✓
```

生成列确认为 `VIRTUAL GENERATED`，表达式与设计一致。

### 4.2 实际拒绝

```
first active created: ok, id= 4
duplicate active rejected by DB:
  (1062, "Duplicate entry 'teacher-4' for key 'uq_r21_active_role'")
after revoke, new active created: ok, id= 6
total rows for account: 2          ← 历史保留
third active after second revoke: ok, id= 7
total rows (history kept): 3
```

### 4.3 并发竞态（4 线程）

```python
barrier = threading.Barrier(4)
# 4 个线程同时 create 同一 (account, role)
self.assertEqual(results.count('ok'), 1)        # 只有 1 个成功
self.assertEqual(active_count, 1)               # DB 里只有 1 个 active
```

`TransactionTestCase` + 真实数据库连接，不是 mock。

### 4.4 迁移可逆

```
index rows before rollback : 4
[rollback workflow]  Unapplying smass_workflow.0003_open_task_unique... OK
[rollback r21]       Unapplying r21_account.0002_active_role_unique... OK
index rows after rollback  : 0
[re-apply all]       Applying both... OK
index rows after re-apply  : 4
```

## 5. 数据安全

`scripts/r10_uniqueness_precheck.py`：

- **只读**查询，不改任何数据
- 检查两个不变量是否已被现有数据违反
- 发现重复时打印明细并返回非零
- 即使直接跑迁移，MySQL 建唯一索引会失败 → **不会删除任何历史行**

实测（`smass_r10_release`）：两表均无重复，预检通过。

## 6. 局限

| 项 | 状态 | 说明 |
|---|---|---|
| MySQL 5.7 兼容 | **NOT TESTED** | 未在 5.7 验证虚拟生成列 + 唯一索引组合 |
| 其他数据库（PostgreSQL/SQLite） | **N/A** | 该迁移用 `RunSQL`，跨库不可移植；本项目只用 MySQL |
| `ApprovalTask` 的 `pending` 状态 | **PARTIAL** | 代码里只有 `open/done/cancelled`；若未来新增 `pending` 需扩展生成列表达式 |
| 死锁重试 | **NOT RUN** | 并发冲突抛 `IntegrityError`，未实现自动重试（当前由调用方处理） |

## 7. 与计划的对应

| 计划要求 | 本报告 |
|---|---|
| 枚举精确不变量 | §1 |
| 检查迁移与真实索引 | §1（`SHOW INDEX` 实测） |
| 比较生成列/应用锁/触发器方案 | §2（选生成列，因 MySQL 无部分索引） |
| 迁移加法且可逆 | §3 §4.4 |
| 遇重复先报告不删数据 | §5 |
| 新库/升级克隆/回滚三处测试 | §4（新库 + 升级克隆见 H5 + 回滚） |
| 并发只产生一个 active | §4.3 |
| 撤销后可新建、历史保留 | §4.2 |
| W036 处理 | §3（state 移除，警告消失） |
