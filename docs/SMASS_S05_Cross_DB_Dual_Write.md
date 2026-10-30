# S05 独立数据库双写与恢复（验收报告）

- 实现：`scripts/pmr_cross_db_dual_write.py`
- 回归：`smass_operations/tests/test_s05_cross_db.py`（3 例，实际执行通过）
- 同库先例（仅逻辑验证）：`docs/SMASS_PMR_Dual_Write_Rollback.md`

## 1. 为什么必须重建

PM4 的双写发生在**同一个数据库**的两组表上，只能验证失败注入与补偿逻辑，
不能代表生产中的跨库/跨系统写入。本任务为 legacy 与 R10 各建**独立数据库**：

| 侧 | 数据库 | 表 |
|---|---|---|
| legacy | `smass_pmr_cross_legacy_*` | `app01_admin` |
| R10 | `smass_pmr_cross_r10_*` | `r21_account_account` + 日志/队列 |

两侧由两个独立的 `pymysql` 连接写入，**没有跨库事务**；
一致性只能靠补偿、持久化队列与对账修复保证。

## 2. 场景与结果

`scenario_all()` 在一次运行中覆盖 9 项检查，实测全部 PASS：

| # | 场景 | 检查 | 结果 |
|---|---|---|---|
| 1 | 双写成功 | 两侧各一行、`status=committed` | PASS |
| 2 | 第二写失败 | 第一写被补偿删除、`status=compensated` | PASS |
| 3 | 补偿失败 | 进入 `pmr_compensation_queue(status=pending)` | PASS |
| 4 | 队列重放 | 队列清空、日志改为 `compensated` | PASS |
| 5 | 幂等重放 | 同幂等键返回首次结果，无第二行 | PASS |
| 6 | 进程异常退出 | 子进程写 legacy 后 `os._exit(9)` | PASS |
| 7 | 漂移修复 | 对账发现 `legacy_only`，修复后 drift=0 | PASS |
| 8 | 不确定提交 | 两侧提交后进程退出，重启按实际状态判定为 `committed` | PASS |
| 9 | 最终一致性 | 全量 drift=0 | PASS |

原始输出位于 `%TEMP%\pmr_cross_db\s05_*.json`（本地证据，不入库）。

## 3. 关键设计

### 3.1 幂等日志

`pmr_cross_log.idempotency_key` 唯一。重放时先查日志：

- `committed` / `compensated` → 直接返回首次结果；
- `compensation_pending` → 允许继续走补偿重放。

### 3.2 补偿队列

```sql
pmr_compensation_queue(idempotency_key, side, payload, status,
                       attempts, last_error, created_at, resolved_at)
```

补偿动作失败不吞异常：把"要删哪一侧、删什么"持久化，恢复后由
`replay_compensation()` 重试；成功后把对应日志改为 `compensated`。

### 3.3 进程崩溃

子进程写入并 `commit` 后直接 `os._exit(9)`，不写日志、不清理。
父进程：

1. `drift()` 按登录名比较两侧集合；
2. `repair_drift()` 对单侧遗留按"未提交"删除（不猜测业务意图）；
3. `resolve_unknown()` 对两侧都存在但无日志的键补写 `committed` 日志。

### 3.4 读一致性

两个连接长时间存活时，MySQL REPEATABLE READ 会造成"新提交数据读不到"。
`_refresh()` 在每次对账/重放前结束当前事务快照，确保看到其他进程的提交。

## 4. 测试

```bash
python manage.py test smass_operations.tests.test_s05_cross_db \
  --settings=smass.settings_r10
```

结果：`Ran 3 tests ... OK`，其中 `test_independent_databases` 通过
`information_schema` 断言 legacy 库**没有** `r21_account_account`、
R10 库**没有** `app01_admin`，防止测试退化为同库双表。

## 5. 未覆盖与边界

| 项 | 状态 | 原因 |
|---|---|---|
| 真实生产跨库/跨系统 | 未执行 | 需正式库写权限，本任务明确不授权 |
| 跨库网络分区 | 未执行 | 单机 MySQL 无法真实模拟网络中断 |
| 高并发竞争 | 部分覆盖 | 幂等键覆盖重复请求；并发压测不在本任务范围 |
| 真实用户数据 | 未使用 | 全部为合成账号 |

本任务只声明"跨库写入失败后的收敛能力"，**不声明分布式事务原子性**。
