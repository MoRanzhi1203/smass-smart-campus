# SMASS R2.2 G6 性能报告（Performance Report）

- 库：`smass_r22_g6_synth`（**全合成数据**，固定种子，无真实姓名/学号/手机号）
- 账号规模：**1,146** 个合成学生账号（100 → 1000 阶梯生成后累计）
- 脚本：`scripts/r22_g6_bench.py`；输出：`%TEMP%\smass_g6_bench\g6_bench.{json,csv}`（**未进 Git**）
- 环境：Python 3.12.16 / Django 5.2.17 / MySQL 8.0.18 / Windows 本机

## 1. 身份解析延迟（size=1146）

| 身份类型 | P50 (ms) | P95 (ms) | P99 (ms) | 每请求 SQL |
|---|---|---|---|---|
| `account` | 0.006 | 0.011 | 0.017 | **0** |
| `legacy` | 0.007 | 0.010 | 0.023 | **0** |
| `dual` | 1.084 | 1.642 | 2.032 | **1** |
| `conflict` | 1.036 | 1.467 | 1.752 | **1** |
| `anonymous` | 0.005 | 0.009 | 0.011 | **0** |
| `scoping`（对象范围查询） | 1.878 | 3.532 | — | **2** |

结论：

- **单身份场景零额外查询**（account/legacy/anonymous 全部 0 SQL）——懒解析 + 请求级缓存生效；
- 只有 `dual`/`conflict` 需要 1 次 `LegacyAccountLink` 查询，P95 均 < 2 ms；
- `scoping` 的 2 条 SQL 是 `COUNT` + 数据查询，属预期。

## 2. 查询增量目标（≤1/请求）

| 场景 | 增量 | 判定 |
|---|---|---|
| account / legacy / anonymous | 0 | **达标** |
| dual / conflict | +1 | **达标**（等于上限） |
| scoping | +2（COUNT + 查询） | 略超 1，属业务查询本身，非身份开销 |

## 3. 规模阶梯

| 目标规模 | 实测账号数 | 状态 |
|---|---|---|
| 100 | 100 | PASS |
| 1,000 | 1,146（含并发测试残留） | PASS |
| 10,000 | — | **NOT RUN**（未在预算内执行） |

> 明确声明：**没有**把 10,000 写成已测值。6 行真实样本与 1,146 合成样本都**不能**代表生产容量。

## 4. 测量缺陷与修正（真实过程）

| 问题 | 现象 | 修正 |
|---|---|---|
| `queries_log` 9000 条上限 | size=1000 时 SQL 计数变成 0 | 每次 capture 前 `connection.queries_log.clear()` |
| 并发 login 跨轮重复 | 假 `IntegrityError` | login 加 `secrets.token_hex(3)` 运行前缀 |
| 错误未分类 | 只知道 `OperationalError` | 记录 `exc.args[0]` errno |

## 5. 与旧路径对照

旧路径（`session['info']` 直读）不产生数据库查询，延迟可忽略。
新身份解析在单身份场景同样 **0 SQL**，因此**没有引入可测量的读放大**；
`dual` 场景的 +1 查询是 `LegacyAccountLink` 映射校验的必要成本。

## 6. 未做

| 项 | 状态 |
|---|---|
| 10,000 规模 | NOT RUN |
| 高频页面端到端延迟（模板渲染） | NOT RUN |
| CPU/RAM 采样 | NOT RUN（未采集，不虚构） |
| 生产数据规模外推 | **不做**（样本不足以外推） |
