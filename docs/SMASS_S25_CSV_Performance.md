# S25-PERF CSV 导出性能优化（验收报告）

- 实现：`smass_organization/export.py`、`smass_organization/views.py`
- 基准：`scripts/s25_csv_perf.py`
- 回归：`smass_organization/tests/test_s25_perf.py`（3 例）
- 关联：`docs/SMASS_Data_Exchange_S25_Contracts.md`

## 1. 结论（同机、同数据、同进程对比）

| 指标 | 旧路径（baseline） | 优化后 | 变化 |
|---|---|---|---|
| 10,000 行耗时 | **41.86 s** | **2.65 s** | **15.8×** |
| 峰值内存 | 26.4 MB | 10.4 MB | 降低 60% |
| SQL 查询数 | ≈ 10,000+（N+1） | **6**（常数） | 与行数解耦 |
| 导出字节 | 370 KB | 490 KB | 优化版包含可见扩展字段 |

> 说明：此前记录的"10k CSV 约 12.5 s"与本次 41.9 s 的差异来自**测量路径不同**：
> 本次 baseline 严格复现旧代码 `list(queryset)` + 每行 `filtered_extra()`，
> 每行都会查询一次 `StudentFieldDefinition`（N+1）。
> 这里不引用 12.5 s 作为本轮基线，避免不同环境的数字混用。

## 2. SQL 与代码分析

旧实现：

```python
rows = list(queryset.order_by('student_no')[offset:offset + limit])
for record in rows:
    visible_extra = services.filtered_extra(record, account)  # 每行一次字段定义查询
```

问题：

1. `list()` 把 10k 模型一次性物化，内存随行数线性增长；
2. `filtered_extra()` 每行调用 `visible_fields()`，后者查询
   `StudentFieldDefinition`，形成 **N+1**；
3. `StringIO` 累积完整文本后才返回，HTTP 响应无法边生成边发送；
4. 旧上限 5,000 行与"10k 导出"目标不一致。

## 3. 优化措施

| 措施 | 实现 | 效果 |
|---|---|---|
| 分批取数 | `queryset.iterator(chunk_size=2000)` | 内存不随总行数线性增长 |
| 字段权限一次计算 | 导出前构造 `allowed_codes` 集合 | 消除 N+1 |
| 逐块生成 | `iter_students_csv()` 逐块 yield | 可对接流式响应 |
| 流式下载 | `student_export?stream=1` → `StreamingHttpResponse` | 首字节更早，服务端不驻留整串 |
| 上限调整 | `MAX_ROWS = 50000` | 覆盖 10k，仍防误触发超大导出 |

权限与安全能力**未回退**：

- 对象范围仍走 `scoped_students(account)`；
- 字段范围仍走 `visible_fields(account)`；
- CSV 公式注入中和 `sanitize_cell()` 保持不变；
- 导出审计 `_audit_export()` 保留。

## 4. 可复现证据

```bash
python scripts/s25_csv_perf.py --json
```

本次输出（节选）：

```json
{
  "rows": 10000,
  "baseline": {"seconds": 41.857, "peak_bytes": 26360221},
  "optimized": {"seconds": 2.647, "peak_bytes": 10420133},
  "speedup": 15.81,
  "memory_ratio": 2.53,
  "optimized_query_count": 6
}
```

回归：

```bash
python manage.py test smass_organization.tests.test_s25_perf \
  --settings=smass.settings_r4
```

结果：`Ran 3 tests ... OK`：

1. 10,001 行（含表头）完整输出；
2. 查询数 > 0 且 ≤ 12（查询预算有效）；
3. 优化路径耗时与内存均低于 baseline，峰值 < 20 MB。

## 5. SLA 与边界

| 项 | 状态 |
|---|---|
| 10k 行目标 | 达到（2.65 s / 10.4 MB / 6 查询） |
| 正式 SLA（如 P95 < 2 s） | **待业务确认**，不臆造 |
| 并发导出压力 | 未测（单进程基准） |
| 50k 行上限 | 未做规模验证 |
| 流式响应中断重试 | 未实现断点续传 |
