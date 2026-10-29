# SMASS PMR Test Report（PM10）

- 基线：`ac238df`
- 测量工具：`scripts/r10_full_regression.py`（**实际跑一遍并统计，不硬编码**）
- 测量时间：PM10 阶段

## 1. 全量回归（实测 930 例）

| 套件 | settings | 用例 | 耗时 | 结果 |
|---|---|---|---|---|
| `smass_operations` | `settings_r10` | **414** | 381.5s | OK |
| `smass_analytics` | `settings_r7` | 31 | 33.1s | OK |
| `smass_organization` | `settings_r4` | 69 | 75.3s | OK |
| `smass_academic` | `settings_r5` | 56 | 74.6s | OK |
| `smass_workflow` | `settings_r6` | 41 | 35.4s | OK |
| `smass_api` | `settings_r8` | 23 | 13.1s | OK |
| `r22_account` | `settings_r22` | 94 | 52.3s | OK |
| `r21_account` | `settings_r21` | 72 | 62.9s | OK |
| `app01` | formal | 114 | 70.4s | OK |
| `tests_e2e` | formal | 16 | 43.0s | OK |
| **合计** | | **930** | ≈14.2 分钟 | **0 失败** |

## 2. 与基线的对比

| 阶段 | 总数 | 增量 |
|---|---|---|
| H0–H9 完成（`ac238df`） | 811 | — |
| PM 阶段新增 | **+119** | PM1 29 + PM2 19 + PM3 15 + PM4 7 + PM5 13 + PM6 13 + PM8 23 |
| **PM10 实测** | **930** | |

`smass_operations` 从 295 增至 **414**（+119），与新增测试文件数一致。

## 3. PM 新增测试明细（119 例）

| 文件 | 例数 | 覆盖重点 |
|---|---|---|
| `test_pmr_pm1_legacy_auth.py` | 29 | 32 位 hex 识别（大写/31/33/非 hex 均不命中）；单次与双重 MD5 兼容；懒惰升级；错误密码不改存储；未知格式不抛异常；限速 5 次/300 秒；旧密钥泄漏三断言 |
| `test_pmr_pm2_fixture.py` | 19 | 三格式编码交叉验证；合成证件/手机不匹配真实正则；权重和为 1；500 抽样覆盖全分支；guard 拒绝非 pmr 前缀；对抗用例齐全 |
| `test_pmr_pm3_migration.py` | 15 | 可用哈希判定；前缀守卫；映射表唯一键与批次索引（真实建表）；计数封顶 200 条 |
| `test_pmr_pm4_dual_write.py` | 7 | 三模式常量互斥；幂等键唯一；批次索引；能表达 compensated 态 |
| `test_pmr_pm5_upgrade_restore.py` | 13 | 前缀契约；`HashCarrier` 可被 `verify_password` 消费并触发升级写入；双指纹确定性 + "插一行必变"；故障点存在 |
| `test_pmr_pm6_bench.py` | 13 | 百分位边界（空/单值/100 序列/单调）；主机画像；`SHOW` 取第二列；多进程契约（必须 `ProcessPoolExecutor` + `os.getpid()`）；隔离级别/死锁/锁等待记录 |
| `test_pmr_pm8_security.py` | 23 | 陈旧 info-only session 四端点全拒；公开页不泄露 info；已认证不被 info 覆盖；强制改密；停用；CSRF；审计载荷；scope 一致 |

## 4. 演练实测（脚本级，非单测）

| 演练 | 规模 | 结果 |
|---|---|---|
| PM2 合成生成 | tiny/medium/1k/10k | 11 / 101 / 1001 / 10001 行；耗时 5s / 14.7s / 82.1s / 940.2s |
| PM3 行迁移 | tiny | created=29，rejected=6，strict_ok=true |
| PM3 行迁移 | 1k | created=2146，78.5s，strict_ok=true |
| PM3 行迁移 | 10k | created=21451，478.9s，strict_ok=true |
| PM3 幂等 | tiny 重跑 | created=**0**，skipped=34 |
| PM4 双写 | 3 模式 | 11 项检查全过；补偿零残留 |
| PM5 升级+恢复 | tiny / 1k | 26→72 表；双指纹一致；登录 4/4 |
| PM5 故障注入 | 3 点 | before_migrate / during_backfill / after_index 全 exit=0 |
| PM6/PM7 基准 | 1k / 10k | 见性能报告；死锁 0 |

## 5. 质量门禁（四层）

| 门禁 | 命令 | 结果 |
|---|---|---|
| PMR 账本 + 证据 + 产物 + 命令日志 | `pmr_gate.py --strict --artifacts --commands` | 见 §6 |
| H0–H9 账本 | `r10_release_hardening_gate.py --strict --artifacts` | 10/10 TESTED |
| R4–R10 账本 | `r4_r10_gate.py --strict` | 36/36 TESTED |
| Django check | `check --settings=smass.settings_r10` | 0 issues |
| 迁移一致性 | `makemigrations --check --dry-run`（formal/r10/r21） | No changes |
| 依赖审计 | `pip-audit -r requirements.txt` | 无已知漏洞 |
| 秘密扫描 | `r9_secret_scan.py` | PASS |

## 6. 测试方法学的三点说明

**1. 不硬编码总数**

`r10_full_regression.py` 逐套件运行并解析 `Ran N tests`，
所以 930 是**本次实测值**，不是从旧报告抄来的。

**2. 测试自身的 bug 不算产品改进**

本轮有 3 个失败是**断言写错**（PM3 对账基准、PM5 index 推断、PM8 `/r10/` 公开页）。
报告里区分"产品缺陷"与"测试缺陷"，不把后者计入修复数。

**3. 环境相关的用例显式跳过**

`test_pmr_pm5_upgrade_restore.FingerprintShapeTests` 需要 `SMASS_DB_PASSWORD`
才能用原生连接做指纹测试。未设置时 `skipUnless` 跳过并**在报告中标注**，
不静默通过。

## 7. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 重跑全部回归（实测总数） | §1（930） |
| 四个门禁 strict | §5 |
| 12 份文档齐全 | 见 `SMASS_PMR_Go_NoGo.md` §3 |
| 三类判定分别给出 | 见 `SMASS_PMR_Go_NoGo.md` §1 |
| 不把未执行标为 TESTED | 全文区分"演练实测"与"未执行" |
