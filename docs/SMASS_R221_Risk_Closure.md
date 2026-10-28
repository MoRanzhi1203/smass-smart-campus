# SMASS R2.2.1 风险收敛（Risk Closure）

> 逐项复核 `R5,R7,R10,R12,R13,R14,R20,R21,R22,R23,R24,R25`，只在有证据时 CLOSED。

## 1. 逐项结果

| ID | 原描述 | 本轮结果 | 证据 |
|---|---|---|---|
| R5 | 审计保留策略未实现 | **MITIGATED** | 提案已成文（90 天登录 / 3 年角色），未实现自动清理（符合"不得自动删除"） |
| R7 | `smass_g5_ro` 长期存在 | **OPEN** | 已列入授权请求；未回收 |
| R10 | `smass_r22_g5_stage` 含真实姓名 | **OPEN** | 未删除、未读取、未复制；清理需授权 |
| R12 | 回滚仅支持全量 | **OPEN** | 未实现按批次回滚；但批次审计已可定位来源批次 |
| R13 | PyMySQL 版本不一致 | **CLOSED** | 全部判断改用 `importlib.metadata`；本轮实测 metadata=1.1.2、`__version__` 不可靠已记录 |
| R14 | 并发触发 1040 | **CLOSED（结论已修正）** | 30/40/50 worker 全部 0 错误；瓶颈是长事务占用连接，非 worker 数 |
| R20 | 旧路由前缀外不桥接 | **OPEN** | 当前只覆盖 `/admin/ /student/ /teacher/` |
| R21 | 桥接产生"伪 legacy 身份" | **MITIGATED** | 仅对有 `LegacyAccountLink` 的账号生效，且不覆盖既有 session；H3 测试锁定 |
| R22 | 并发容量未知 | **CLOSED** | 实测 5–50 worker 全成功，服务端 `max_connections=20` 已定位 |
| R23 | 10000 规模未测 | **CLOSED** | 10,000 回填/回滚/二次回填/一致性 全 PASS |
| R24 | 跨浏览器未测 | **MITIGATED** | WebKit 27.2 已测 5/5；Firefox 仍 NOT RUN |
| R25 | 审计表无限增长 | **MITIGATED** | 保留策略提案 + 索引 `batch_id`；未实现清理 |

## 2. 汇总

| 状态 | 数量 | ID |
|---|---|---|
| **CLOSED** | 5 | R13、R14、R22、R23 + （R6 已于上轮关闭） |
| **MITIGATED** | 4 | R5、R21、R24、R25 |
| **OPEN** | 3 | R7、R10、R12、R20（4 项） |

实际 OPEN：**R7、R10、R12、R20**（4 项），全部**不影响技术就绪**：

- R7/R10：清理类，需授权；
- R12：回滚粒度，当前批次审计已提供定位能力；
- R20：桥接覆盖范围，可通过增加前缀扩展。

## 3. 无高危未决项

本轮未发现新的高危安全缺陷。
WebKit 的 LiveServer 竞态属测试基础设施，已隔离在测试代码内并注释说明。

## 4. 审计与身份保护稳定性

| 检查 | 结果 |
|---|---|
| `django_admin_log` 外键误用 | 未发生（审计走 `AccountAuditEvent`） |
| 冲突身份拒绝 | H2/H3/H4 + 浏览器均验证 |
| 停用账号降级 | H3 验证为拒绝 |
| 审计写失败告警 | `safe_record` + `alerts.audit_failure` |
