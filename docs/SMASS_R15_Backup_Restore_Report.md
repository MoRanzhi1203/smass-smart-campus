# SMASS R1.5 备份与恢复报告（Backup & Restore Report）

- 目标库：`smass`（开发种子库，26 表 / 158 行）
- 备份目录：`E:\PythonWeb\_smass_db_backup`（**项目外**，不进入 Git）
- 结论：**备份可生成、可在隔离库完整恢复、外键与迁移记录一致**；自动定时任务仅提供脚本，**未注册系统计划任务**（需授权）

## 1. 源码备份 ≠ 数据库备份

| 类型 | 位置 | 说明 |
|---|---|---|
| 源码 | Git 分支 + `_smass_backups\smass_src_*.zip` | 只含代码，**不含任何数据** |
| 数据库 | `_smass_db_backup\smass_db_<ts>.sql` + `.meta.json` | 本轮新增，含 schema + 数据 |

> 上一轮仅有源码 zip，不能用于数据恢复。本轮补上真正的数据库备份。

## 2. 备份前置核验

| 项 | 结果 |
|---|---|
| `smass` 用途 | 开发种子库（无真实用户数据） |
| 账号权限 | `root` 具备 RELOAD/LOCK TABLES/SELECT 等，`mysqldump --single-transaction` 无需额外授权 |
| `mysqldump` | `D:\mysql-8.0.18-winx64\bin\mysqldump.exe`，Ver 8.0.18（与服务器一致） |
| 磁盘 | E: 剩余 427.5 GB |
| 凭据处理 | 从 `.env` 读取 → 写入临时 `--defaults-extra-file` → 用完删除；**不出现在命令行/日志/报告** |

## 3. 备份实现

`scripts/db_backup.ps1`

- 源库白名单：仅 `smass`，其他库名直接 `exit 2`；
- `--single-transaction --quick --routines --triggers --events --hex-blob --set-gtid-purged=OFF --no-tablespaces`；
- 不使用 `--databases`（避免导出 `CREATE DATABASE`/`USE`，便于恢复到任意库名）；
- 备份物校验：文件 > 4 KB 且 `CREATE TABLE` 数量 ≥ 26，否则失败退出；
- 输出脱敏元数据 `.meta.json`（库名、时间、字节数、CREATE/INSERT 计数、驱动版本、host/port/user，**无口令**）。

### 3.1 实测结果

```
mysqldump exit code : 0
size          : 34,908 bytes
CREATE TABLE  : 26
INSERT INTO   : 15
[PASS] backup done
```

共生成 3 份备份（首次 + 定时脚本冒烟 + 演练用），产物结构一致。

## 4. 隔离恢复演练

`scripts/db_restore_drill.ps1` + `scripts/db_verify.py`

### 4.1 防误连（双层）

| 层 | 规则 |
|---|---|
| PowerShell | 目标库必须 `smass_restore_drill_*`；源库固定 `smass`；DROP 前再次校验前缀 |
| Python `assert_safe_target()` | 拒绝 `smass` / `test_smass` / `mysql` / `sys` / `information_schema` / `performance_schema`，且必须命中白名单前缀 |

**负向测试实测**（全部按预期拒绝，退出码 2）：

```
target=smass        exit=2
target=test_smass   exit=2
target=mysql        exit=2
target=school       exit=2     ← 实例上的真实业务库
target=badname      exit=2
target=smass_restore_drill_20261027   exit=0   ← 白名单通过
```

### 4.2 演练结果

```
=== create drill db: smass_restore_drill_20261027_135343 ===
[OK] drill db created
=== import backup ===
[OK] import done
--- SOURCE ---  tables: 26  foreign_keys: 24  migrations: 22  total rows: 158
--- TARGET ---  tables: 26  foreign_keys: 24  migrations: 22  total rows: 158
[PASS] 表清单、行数、迁移记录、外键数量完全一致
[PASS] restore drill ok
=== drop drill db ===
[OK] drill db dropped (source smass untouched)
drill_exit=0
```

**门禁达成：至少一次真实隔离恢复成功。**

## 5. 演练中发现并修复的两个真实缺陷

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 首次演练报 `[WARN] drop failed`，且**演练库真的残留**（`smass_restore_drill_20261027_135259`） | `DROP DATABASE \`name\`;` 在 `cmd /c` 下反引号被处理异常；脚本还错误地用 cmd 退出码判定成功 | 去掉反引号 + 改为查询 `information_schema.SCHEMATA` 以**事实**判定库是否消失；残留库已手动清理 |
| 2 | `Start-Process` 抛 `ArgumentException: Item has already been added. Key: 'NO_PROXY'` | PowerShell 5.1 在环境中存在大小写不同的同名变量（`NO_PROXY`/`no_proxy`）时的已知缺陷 | 全部改用 `cmd /c` 做字节级重定向，并避免 `Start-Process` |

清理后复核：`smass` 仍为 26 表 / 24 外键 / 22 迁移 / 158 行，实例 29 个库数量不变。

## 6. 定时备份

`scripts/db_backup_scheduled.ps1`：调用备份脚本 → 按 `-RetentionDays`（默认 14）清理过期 `.sql`/`.meta.json` → 写 `logs/db_backup.log`（脱敏）。

冒烟实测：

```
[2026-10-27T13:54:12] scheduled backup start
[PASS] backup done: E:\PythonWeb\_smass_db_backup\smass_db_20261027_135413.sql
[2026-10-27T13:54:14] db_backup exit=0
[2026-10-27T13:54:14] retention removed=0 keep_days=14
[2026-10-27T13:54:14] scheduled backup done
```

### 6.1 部署状态：**待部署（未注册计划任务）**

计划要求"只有在明确授权时才真正创建系统计划任务"。本轮**未创建**。部署步骤（需管理员 PowerShell）：

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "E:\PythonWeb\smass\scripts\db_backup_scheduled.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 02:30
Register-ScheduledTask -TaskName 'SMASS-DB-Backup' -Action $action -Trigger $trigger `
  -Description 'SMASS 每日数据库备份' -User $env:USERNAME
```

验收：`Get-ScheduledTask SMASS-DB-Backup` 存在；次日检查 `logs/db_backup.log` 有新记录。

## 7. 保留策略与恢复点

| 项 | 值 |
|---|---|
| 备份位置 | `E:\PythonWeb\_smass_db_backup`（Git 忽略） |
| 保留 | 默认 14 天（脚本参数可调） |
| 恢复点粒度 | 每次备份一个 `.sql` + `.meta.json` |
| 恢复演练 | 任意备份文件可重复演练，目标库名自动带时间戳 |

## 8. 结论

| 任务 | 状态 | 证据 |
|---|---|---|
| A-1 区分源码/数据库备份 | PASS | 本报告 §1 |
| A-2 前置核验 | PASS | §2 |
| A-3 一致性备份 | PASS | 34,908 bytes / 26 CREATE TABLE |
| A-4 隔离恢复演练 | PASS | 26 表/24 外键/22 迁移/158 行完全一致 |
| A-5 备份/恢复脚本 | PASS | `db_backup.ps1` / `db_restore_drill.ps1` / `db_verify.py` |
| A-6 定时备份 | **部分完成** | 脚本与冒烟 PASS；**计划任务未注册（待授权）** |
| A-7 防误连 | PASS | 5 个负向用例全部 exit 2 |
