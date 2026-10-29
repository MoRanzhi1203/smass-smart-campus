# SMASS PMR GO / NO-GO（PM10）

- 基线：`ac238df`
- 分支：`feat/smass-r4-r10-integrated-platform`
- 实测回归：**930 例全绿**（10 套件）

## 1. 三类判定（分别给出，互不替代）

```
SYNTHETIC_MIGRATION_TECHNICAL_GO  = YES
REAL_DATA_DRILL_PENDING_AUTH      = AWAITING_EXPLICIT_AUTHORIZATION
PRODUCTION_DEPLOYMENT             = NOT_AUTHORIZED
```

**为什么必须分开**：

- 合成数据证明了**代码路径正确**，但没证明**真实数据形态可处理**
- 真实数据演练通过也只证明**数据可迁移**，不证明**可以上线**
- 生产部署还需：BD-05..08 业务规则、性能优化、回滚预案演练、变更窗口

## 2. PM0–PM10 状态

| ID | 任务 | 状态 | 关键证据 |
|---|---|---|---|
| PM0 | 基线审计 | **TESTED** | HEAD/branch/26 表/11 条 settings 映射；发现已实现的旧密码兼容 |
| PM1 | 旧密码兼容 | **TESTED** | 29 例；单次/双重 MD5 + 懒惰升级；密钥泄漏固化 |
| PM2 | 合成数据集 | **TESTED** | 19 例 + 四规模；确定性指纹；无 PII 自校验 |
| PM3 | 行迁移与对账 | **TESTED** | 15 例；tiny/1k/10k 均 strict_ok；幂等 created=0 |
| PM4 | 双写与回滚 | **TESTED** | 7 例 + 11 项检查；补偿零残留 |
| PM5 | 升级与恢复 | **TESTED** | 13 例；双指纹一致；三故障点全过 |
| PM6 | 性能与锁 | **TESTED** | 13 例；1k/10k 实测；死锁 0 |
| PM7 | 多进程并发 | **TESTED** | 7/11 个真实 PID；不变量成立 |
| PM8 | 安全与会话 | **TESTED** | 23 例；陈旧 session 全拒 |
| PM9 | 授权包 | **TESTED**（文档） | 列级清单/审批矩阵/脱敏/TTL/runbook；**未执行** |
| PM10 | 最终判定 | **TESTED** | 本文件 |

**11/11 TESTED。**

注意 PM9 的 TESTED 指"授权包文档已完成并通过门禁"，
**不是**"真实数据演练已执行"——后者是 `REAL_DATA_DRILL_PENDING_AUTH`。

## 3. 12 份文档

| # | 文档 | 状态 |
|---|---|---|
| 1 | `SMASS_PMR_Executive_Report.md` | ✓ |
| 2 | `SMASS_PMR_Legacy_Auth_Compatibility.md` | ✓ |
| 3 | `SMASS_PMR_Synthetic_Data_Spec.md` | ✓ |
| 4 | `SMASS_PMR_Row_Migration_and_Reconciliation.md` | ✓ |
| 5 | `SMASS_PMR_Dual_Write_Rollback.md` | ✓ |
| 6 | `SMASS_PMR_Upgrade_Restore_Drill.md` | ✓ |
| 7 | `SMASS_PMR_Performance_and_Concurrency.md` | ✓ |
| 8 | `SMASS_PMR_Security_and_A11y.md` | ✓ |
| 9 | `SMASS_PMR_Real_Data_Authorization_Package.md` | ✓ |
| 10 | `SMASS_PMR_Go_NoGo.md` | ✓（本文件） |
| 11 | `SMASS_PMR_Test_Report.md` | ✓ |
| 12 | `SMASS_PMR_Change_Log.md` | ✓ |

## 4. 为什么合成数据可以给 GO

| 理由 | 证据 |
|---|---|
| 旧密码三种格式都能校验并升级 | PM1 29 例，单次/双重 MD5 + PBKDF2 |
| 迁移幂等，重跑不产生重复 | PM3：第 2 轮 created=0 / skipped=34 |
| 对账严格，6 项校验全过 | PM3：tiny 与 1k 均 strict_ok |
| 双写失败能补偿，零残留 | PM4：`compensated=legacy`，两侧残留 0 |
| 备份恢复双指纹一致 | PM5：结构 + 数据指纹都相等 |
| 三个故障点都不破坏源库 | PM5：每次 recovery 三项 unchanged |
| 并发不破坏唯一性不变量 | PM7：active ≤ 1，死锁 0 |
| 陈旧会话没变成后门 | PM8：4 个受保护端点全拒 |
| 回归 930 例全绿 | PM10 实测 |

## 5. 为什么真实数据仍是 PENDING

| 阻断项 | 具体缺失 |
|---|---|
| PII 读取授权 | PM9 §4 审批矩阵**未签字** |
| 只读账号 | 未创建（需 DBA 配合） |
| 脱敏脚本评审 | 未评审（需安全负责人） |
| 样本范围确认 | 未确认（需数据责任人） |

**技术路径完全清楚**（PM3/PM5 已证明），只差授权。

## 6. 为什么生产仍是 NOT_AUTHORIZED

| 阻断项 | 说明 |
|---|---|
| 真实行迁移未做 | R-16，需 PM9 授权 |
| 旧密钥泄漏 | 需强制改密策略（业务+安全共同决定） |
| CSV 导出 10k 需 12.5s | 性能不可接受，需优化 |
| BD-05..08 未输入 | 学籍状态/层级/1:1/停用规则未定 |
| 生产量级未压测 | 10 万+ 行未测 |
| 回滚预案未在真实拓扑演练 | 只在隔离库验证 |

## 7. 风险登记（PM 阶段新增/更新）

| ID | 风险 | 等级 | 状态 |
|---|---|---|---|
| R-16 | 真实行迁移未做 | **中** | `REAL_DATA_DRILL_PENDING_AUTH` |
| R-17 | 旧 MD5 密钥泄漏 | **中** | 已固化；需强制改密策略 |
| R-26 | CSV 导出 12.5s（10k） | **中** | 已实测；未优化 |
| R-27 | BD-05..08 业务规则缺失 | **中** | 未输入 |
| R-28 | 生产量级未压测 | **中** | NOT RUN |
| R-29 | 进程 kill 后自愈未验证 | **低** | NOT RUN |
| R-30 | 跨 MySQL 版本未验证 | **低** | 仅 8.0.18 |
| R-15 | WebKit 同进程多类失败 | **低** | 可规避（独立进程） |
| R-18 | 屏幕阅读器实机未测 | **中** | NOT RUN |

**高危：0 项。**

## 8. 运维 runbook（摘要）

详见 `SMASS_PMR_Upgrade_Restore_Drill.md` 与 `SMASS_PMR_Real_Data_Authorization_Package.md`。

关键三条：

1. **升级必须复制 `django_migrations` 记录**（否则 `1050 Table already exists`）
2. **应用连接用 READ COMMITTED**（否则 `update_last_login` 在并发下 500）
3. **双写必须有补偿**（跨库无法原子；不补偿会产生"旧有新无"的账号）

## 9. 下一步（按优先级）

| 优先级 | 事项 | 谁 |
|---|---|---|
| P0 | 签署 PM9 审批矩阵 | 数据责任人 / 安全 / DBA / 项目负责人 |
| P0 | 输入 BD-05..08 | 业务方 |
| P1 | 决定 CSV 导出优化 | 开发 |
| P1 | 决定旧密钥强制改密策略 | 安全 + 业务 |
| P2 | 生产量级压测（10 万+） | 开发 + DBA |

## 10. 最终声明

**本轮交付的是"合成数据上的迁移技术就绪"与"真实数据的授权申请"。**

不声明以下任何一项：
- 真实数据可迁移（未执行）
- 可以部署生产（未授权）
- 性能达标（CSV 导出 12.5s 未优化）
- 业务规则完备（BD-05..08 未输入）

**PASTE_FINAL_SHA_PLACEHOLDER**
