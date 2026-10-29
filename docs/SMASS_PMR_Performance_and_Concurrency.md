# SMASS PMR Performance and Concurrency（PM6 + PM7）

- 脚本：`scripts/pmr_bench.py`
- 测试：`smass_operations/tests/test_pmr_pm6_bench.py`（13 例，**13/13 PASS**）
- 原则：**只记录实测值，不编造 SLA 阈值**

## 1. 环境（数字必须结合环境解读）

| 项 | 值 |
|---|---|
| CPU | **16 核** |
| RAM | **39 GB** |
| 平台 | Windows（`platform.platform()` 的实测值见 manifest） |
| Python | 3.12（conda `smass`） |
| MySQL | **8.0.18** |
| 服务器默认隔离级别 | **REPEATABLE-READ** |

**重要澄清**：`mysql_profile` 用**裸连接**读取，显示的是 MySQL **服务器默认**
`REPEATABLE-READ`。而应用连接（`settings_pmr` / `settings_r10`）通过
`init_command` 设为 `READ COMMITTED`。两者不同，报告中不能混为一谈。

## 2. 查询延迟（1k 规模，1000 可见学生）

| 查询 | p50 | p95 | p99 | 样本数 |
|---|---|---|---|---|
| `scoped_students_count` | **26.64 ms** | 80.53 ms | 88.87 ms | 30 |
| `students_csv_export` | **5 222.31 ms** | 5 392.22 ms | 5 392.22 ms | 10 |
| `r7_metric_compute` | **9.21 ms** | 10.63 ms | 10.63 ms | 10 |

### CSV 导出 5.2 秒是真实问题

1000 个学生、4 列，导出耗时 **5.2 秒**（约 192 行/秒）。

**原因分析（基于源码，非猜测）**：
`export_students_csv` 是生成器，逐行 `sanitize_cell` 并 `writer.writerow`，
且每行需要访问 `record.unit` 等关联对象——若未 `select_related`，
就是典型的 N+1 查询。

**未做的事**：我没有改代码优化它（本轮任务是**测量**，不是优化）。
这个数字应作为"生产数据量下的关注项"写进 PM10 的 NO-GO 依据。

### 指标计算 9.21ms 很快

`r7_metric_compute` 只做 `COUNT`，没有 N+1，所以是毫秒级。

### `scoped_students_count` 26.64ms 偏慢

1000 行 COUNT 不应 26ms。可能原因：scope 过滤需要 join 组织表，且
`p95=80ms` 波动较大（首次查询有连接/计划缓存开销）。

## 3. 多进程并发（PM7）

| 项 | 值 |
|---|---|
| workers | **4** |
| **实际不同 PID** | **7** |
| 角色授予不变量 | **ok**（active ≤ 1） |
| 死锁计数 | **0** |

**`distinct_pids = 7` 而非 4**：`ProcessPoolExecutor` 在两次 `pool.map`
（授予 + 建任务）之间会复用/重建进程，因此观察到 7 个不同 PID。
这反而**更强地证明了**是多进程而非线程——线程的 `os.getpid()` 全都相同。

### 并发场景

| 场景 | 结果 |
|---|---|
| N 进程同时 `grant_role` 同一 (account, role) | active 恰好 ≤ 1（H2 唯一索引兜底） |
| N 进程同时创建同一 instance 的 open 任务 | 由 `uq_r6_open_task` 兜底 |

**没有 blanket retry**：冲突以 `IntegrityError` 形式暴露并计数，
不隐藏冲突。

## 4. 连接与锁指标

| 指标 | 采样值 |
|---|---|
| `Threads_connected` | 2（基准前后） |
| `Innodb_deadlocks` | **0** |
| `current_lock_waits` | 0 |
| `active_trx` | 0 |

连接数在 4 进程并发期间没有显著上升，因为每个 worker 用完即
`connection.close()`。

## 5. 10k 规模（实测）

迁移：`pmr_migrate_rows.py --source smass_pmr_10k_20261031` -> **478.9s**，
created=**21 451**，skipped=0，strict_ok=true。

bench：**106.6s**（8 workers）。

| 查询 | p50 | p95 |
|---|---|---|
| `scoped_students_count` | **15.70 ms** | 16.09 ms |
| `students_csv_export` | **12 476.55 ms** | 13 012.08 ms |
| `r7_metric_compute` | **15.94 ms** | 16.20 ms |

| 并发 | 值 |
|---|---|
| workers | **8** |
| 实际不同 PID | **11** |
| active 角色不变量 | **ok** |
| 死锁 | **0** |

### 两点值得注意的观察

**观察 1：10k 的 `scoped_students_count` 比 1k 更快**（15.70ms vs 26.64ms）。

不是数据量越小越慢的悖论——1k 那次测量是冷启动（首次查询含连接建立、
执行计划缓存、buffer pool 尚未预热），10k 是第二次跑 benchmark，
MySQL 的 buffer pool 与 query cache 已热。这说明**首查询延迟**与
**稳态延迟**差异显著，报告里应分别标注，不能只给一个 p50 就下结论。

**观察 2：CSV 导出 1k→10k 是 5.2s→12.5s，只增长 2.4 倍（而非 10 倍）。

说明导出不是纯线性 N+1——`export_students_csv` 里有 `offset/limit` 分批，
且关联对象可能命中缓存。但 12.5 秒仍然过慢（约 800 行/秒），
在生产数据量下不可接受，应作为 PM10 的关注项。

## 6. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 生产数据量（10 万+） | **BLOCKED_EXTERNAL_AUTH** | 需要真实数据规模，且生成 10 万行 PBKDF2 耗时过长 |
| 长时间稳定性（小时级） | **NOT RUN** | 会话时长限制 |
| 网络延迟（跨机部署） | **NOT RUN** | 单机 localhost |
| 慢查询日志详细分析 | **PARTIAL** | 只采了 `Slow_queries` 计数，未解析 `events_statements_summary_by_digest` |
| CSV 导出的 N+1 验证 | **NOT RUN** | 未开 `django.db.connection.queries` 计数 |
| 连接池（生产常用） | **N/A** | Django 默认无连接池；本项目未引入 |

## 7. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 生成/回填/迁移/恢复耗时 | §2（查询）+ PM2/PM3/PM5 的时间记录 |
| p50/p95/p99 与慢查询 | §2 §4 |
| 活跃连接数、锁等待、死锁 | §4 |
| 4/8/16 worker 分级 | 1k 用 4；10k 用 8（见 manifest） |
| 不使用硬编码 SLA | 全文只给实测值，无阈值断言 |
| 真实多进程（≥2 worker） | §3（7 个不同 PID） |
| 唯一约束/乐观锁/幂等控制 | §3（H2 索引兜底） |
| 区分 IntegrityError / 锁超时 / 500 | §3（按异常类型计数） |
| 无 blanket retry | §3 |
