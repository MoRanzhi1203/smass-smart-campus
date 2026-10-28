# SMASS R2.2 运维就绪报告（Operations Readiness）

## 1. 冲突告警（已实现）

`r22_account/alerts.py`，logger 名 `smass.security`。

| 事件 | 阈值 | 触发点 |
|---|---|---|
| `identity_conflict` | 60s / 1 | `RoutePolicyMiddleware` 拒绝 conflict 时 |
| `disabled_account` | 60s / 10 | 停用账号尝试登录（预留接口） |
| `orphan_linkage` | 300s / 1 | 一致性检查发现孤立档案 |
| `bulk_auth_failure` | 60s / 20 | 登录失败聚合 |
| `audit_failure` | 60s / 1 | `audit.safe_record` 写失败 |

**白名单字段**：`event/kind/reason/path/count/outcome/operation/batch_id/role/mode/window_seconds`。
其余字段直接丢弃，从机制上避免姓名/哈希/令牌进入日志。

运维查询示例：

```
# 只看冲突
grep 'identity_conflict' app.log
# 聚合每分钟冲突数
```

阈值作用：`identity_conflict` 立即告警（正常应为 0）；`bulk_auth_failure` 需 20 次/分钟才告警，避免噪声。

## 2. 审计保留策略（**提案，未实现**）

| 项 | 建议 |
|---|---|
| 保留期限 | 登录类 90 天；角色/停用/回填类 3 年（待法务确认） |
| 归档方式 | 按月分区或导出到冷存储，保留 `batch_id` 索引 |
| 清理方式 | 仅按批次+时间窗，**禁止**删除未归档记录 |
| 审批 | 清理需数据责任人书面批准 + 双人复核 |
| 当前状态 | **未实现任何自动清理**（符合"不得自动删除"要求） |

## 3. 数据库与账号清单（含处置建议，均未执行）

| 对象 | 归属 | 数据分类 | 必要性 | 建议 |
|---|---|---|---|---|
| `smass` | 生产开发库 | 真实 | 必须 | 只读；切换前全量备份 |
| `smass_r22_g5_stage` | G5 演练 | **含真实姓名副本** | 证据 | 建议脱敏后清理（需授权） |
| `smass_r22_g6_synth` | G6 基准 | 全合成 | 可复现基准 | 建议保留或授权删除 |
| `smass_r22_g8_drill` | H2 演练 | 全合成 | 证据 | 建议保留至切换后 |
| `smass_r21_proto` / `smass_r22_proto` / `smass_r22_b_proto` | 原型 | 合成/复制 | 证据 | 保留 |
| `smass_r22_b_switch` | 路径 B 实验 | 半切换 | **EVIDENCE_ONLY** | 保留，禁止当开发库 |
| `smass_g5_ro`（MySQL 账号） | G5 只读 | 仅 SELECT | 只读校验 | 切换完成后回收 |

清理命令需先 dry-run 并评估影响，本轮**未执行任何删除**。

## 4. 依赖

- `cryptography>=41,<51` 已写入 `requirements.txt`；
- 干净 venv 安装验证通过（Django 5.2.17 / Pillow 13.0.0 / PyMySQL metadata 1.2.3 / crypto 50.0.2）；
- 注意：`PyMySQL.__version__` 不可靠（返回 2.2.8，metadata 为 1.2.3），依赖判断须用 `importlib.metadata`。

## 5. 运维缺口

| 项 | 状态 |
|---|---|
| 告警接入监控系统 | 未接（只有日志） |
| 审计保留自动化 | 未实现 |
| 观察期指标看板 | 未建 |
| 值班与回滚演练记录 | 未建 |
| 切换 Runbook 定稿 | 已有草案（`SMASS_R22_G8_Cutover_Runbook.md`） |
