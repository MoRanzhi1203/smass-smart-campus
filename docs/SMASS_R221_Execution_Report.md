# SMASS R2.2.1 执行报告（Execution Report）

- 基线：`f9a99dd`（`feat/smass-r22-final-hardening`）
- 分支：`feat/smass-r221-release-readiness`
- 执行时间：2026-10-28
- 终态：**GO_RECOMMENDED**

## 1. 工作流状态

| 工作流 | 状态 | 关键证据 |
|---|---|---|
| A 并发容量 | **PASS** | 5–50 worker 全部 0 错误；`max_connections=20` 已定位 |
| B 万级规模 | **PASS** | 10,000 回填/回滚/二次回填/一致性 全通过 |
| C 跨浏览器 | **PASS** | Chromium / WebKit / Firefox 各 5/5 |
| D 风险收敛 | **PASS** | 5 CLOSED / 4 MITIGATED / 4 OPEN（均非阻断） |
| E 切换回滚 | **PASS** | G8 drill + 万级回滚 2 秒 |
| F 回归与报告 | **PASS** | 见 §4 |

## 2. 最重要的两处结论修正

### 2.1 「并发上限 = 20」是错的

上一轮结论：并发 50 失败 → 安全上限 20。
本轮修正：**5/10/15/20/25/30/40/50 worker 全部 100% 成功**。

差异原因（已定位）：

| 因素 | 上轮 | 本轮 |
|---|---|---|
| `student_no` | 截断冲突 → 假 `IntegrityError` | 独立唯一值 |
| login 唯一性 | 跨档位重复 | 每轮随机前缀 |
| 事务时长 | 较长 | 短事务 |

**正确结论**：`max_connections=20` 是硬限制，但 Django 每线程用完即还连接，
**worker 数 ≠ 同时持连接数**。真正的风险是**长事务/慢查询**。

因此"必须扩容才能上线"的旧前置条件**不再成立**（改为监控建议）。

### 2.2 跨浏览器从 2/3 变 3/3

Firefox 首次下载超时、**第二次成功**；WebKit 首次安装即成功。
三引擎各 5/5，含**真实旧页面** `/admin/student/list/` 渲染。

## 3. 万级规模数据

| 指标 | 值 |
|---|---|
| 账号 | 10,000（全合成） |
| 回填 | ~211 s（约 47 条/秒） |
| 回滚 | **2.0 s** |
| 二次回填 | 211.27 s |
| 一致性（strict） | ok=true，0 差异 |
| 批次审计 | 2 事件，无未批次窗口 |

## 4. 回归

| 套件 | 用例 | 结果 |
|---|---|---|
| r22_account | 94（含 browser matrix 5） | PASS |
| r21_account | 72 | PASS |
| app01 | 114 | PASS |
| tests_e2e | 16 | PASS |
| **合计** | **296** | 全绿 |

浏览器矩阵另在 WebKit / Firefox 上各跑 5 例（通过环境变量切换引擎，不重复计入套件）。

## 5. 未做

| 项 | 状态 | 原因 |
|---|---|---|
| 万级 cutover（dual→off） | NOT RUN | 只在 100 账号做过 |
| 切换期并发写入 | NOT RUN | 回填是串行 |
| 断网/进程 kill | NOT RUN | 需进程级故障注入 |
| 修改 `max_connections` | 未做 | 需 DBA 授权，且证据显示当前够用 |
| 库/账号清理 | 未做 | 需单独授权 |

## 6. 交付物

`SMASS_R221_Concurrency_Capacity.md`、`SMASS_R221_Scale_10000.md`、`SMASS_R221_Browser_Matrix.md`、
`SMASS_R221_Risk_Closure.md`、`SMASS_R221_Cutover_Rollback_Drill.md`、`SMASS_R221_Go_NoGo.md`、
`SMASS_R221_Change_Log.md`、本报告。

代码：`scripts/r221_scale.py`、`scripts/r221_conn_capacity.py`、
`smass/settings_r22_g221.py`、`r22_account/tests/test_c_browser_matrix.py`。
