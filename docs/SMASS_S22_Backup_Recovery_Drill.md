# S22 备份恢复与 RPO/RTO 演练

> 状态：**TESTED**（真实 mysqldump → 恢复 → 逐表哈希校验，PASS）
> 脚本：`scripts/s22_backup_restore_drill.py`、`smass/settings_s22.py`
> 证据：`.local/evidence/s22/s22_drill_report.json`、`.local/evidence/s22/s22_backup.sql`

## 1. 目标与定义

| 指标 | 定义 | 本项目目标 |
|---|---|---|
| **RPO**（恢复点目标） | 可接受的数据丢失时间窗 | ≤ 15 分钟（对应 binlog/增量备份周期） |
| **RTO**（恢复时间目标） | 从故障到服务可用 | P1 ≤ 4 小时；单库恢复 ≤ 30 分钟 |

演练必须在**隔离库**完成，绝不触碰正式库 `smass`。

## 2. 演练设计

1. **隔离库**：脚本硬校验库名必须以 `smass_s22_` 开头，命中 `smass` 或业务库立即退出；
2. **建库与迁移**：`smass_s22_drill` → `manage.py migrate --settings=smass.settings_s22`（45 张表）；
3. **合成数据**：3 个组织单元 + 20 条学籍（含 `extra.phone`）；
4. **备份**：`mysqldump --single-transaction --routines --triggers`（一致性快照，不锁表）；
5. **恢复**：建 `smass_s22_drill_restored`，用 `mysql` 客户端导入同一份 SQL；
6. **校验**：逐表比对**行数**与**内容 SHA-256**（按主键排序后序列化，结果确定）；
7. **计时**：记录备份耗时、恢复耗时、RTO（全流程）、RPO（最后写入→恢复完成）；
8. **清理**：默认删除两个临时库，只保留 SQL 与 JSON 证据。

安全细节：数据库密码通过 `MYSQL_PWD` 环境变量传递，不出现在命令行与日志。

## 3. 实测结果（2026-10-30）

| 项目 | 结果 |
|---|---|
| 演练库 | `smass_s22_drill` → `smass_s22_drill_restored` |
| 表数量 | 45 |
| 源行数 / 恢复行数 | 247 / 247 |
| 校验差异 | **无** |
| 备份耗时 / 大小 | 2.00 s / 67,341 字节 |
| 恢复耗时 | 2.38 s |
| **RTO** | **18.23 s**（含建库、迁移、灌数、备份、恢复、校验） |
| **RPO** | **4.60 s** |
| 演练后库清理 | 已删除（`SHOW DATABASES LIKE 'smass_s22%'` 为空） |
| 正式库 | `smass` 全程只读、未受影响 |

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py scripts\s22_backup_restore_drill.py --self-test
& $py scripts\s22_backup_restore_drill.py --json .local\evidence\s22\s22_drill_report.json
```

## 4. 结论与生产建议

1. **单库恢复能力已验证**：45 表 247 行全量恢复耗时 2.38 s，校验零差异；
2. 正式库数据量远大于演练库，RTO 会随数据量近似线性增长；建议按正式库 10% 规模再做一次抽样演练；
3. **备份策略建议**：
   - 每日 02:00 全量 `mysqldump`（保留 14 天）+ 每 15 分钟 binlog 归档（满足 RPO ≤ 15 分钟）；
   - 备份文件异地存储，并每日做一次 `restore --dry-run` 校验（表数量 + 关键表行数）；
4. **恢复演练周期**：每季度一次，纳入运维日历；每次演练产出与本文件同结构的报告。

## 5. 已知边界

1. 未演练**时间点恢复**（PITR，需 binlog + `mysqlbinlog`），仅验证了全量 dump 路径；
2. 未做跨主机/异地恢复（同机同实例，网络与 IO 差异未覆盖）；
3. 备份文件未加密与签名（生产应使用 `--ssl-mode` + 落盘加密）；
4. 演练未包含大表（百万行级）的耗时曲线，需在预发环境补测。
