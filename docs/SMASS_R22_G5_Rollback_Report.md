# SMASS R2.2 G5 回滚与恢复报告（Rollback Report）

- 演练库：`smass_r22_g5_stage`（隔离）
- 命令：`manage.py backfill_accounts_r21 --rollback --settings=smass.settings_r22_g5`
- 驱动脚本：`scripts/r22_g5_drill.py`

## 1. 故障注入（单行失败不污染整批）

| 注入点 | 结果 |
|---|---|
| `StudentProfile.objects.create` 抛错 | 该学生行**整体回滚**（无 Account、无 Link、无 Profile）；管理员与教师仍成功（`accounts=2`） |
| 重复学号（已存在） | `DualWriteError` / 冲突计数，不覆盖 |
| 未知登录名改密 | `DualWriteError` |

详见 `r22_account/tests/test_g5_backfill.py::FaultInjectionTests`。

## 2. 回滚范围（关键安全验证）

演练前在 stage 手工建一个"预存账号" `G5_PREEXISTING`（无 `LegacyAccountLink`），然后执行 `--rollback`：

| 指标 | 回滚前 | 回滚后 |
|---|---|---|
| accounts | 7 | **1** |
| links | 6 | 0 |
| roles | 6 | 0 |
| student_profiles | 3 | 0 |
| teacher_profiles | 2 | 0 |

| 断言 | 结果 |
|---|---|
| 预存账号存活 | **PASS**（`preexisting_survived=true`，pk=7） |
| 被删账号全部是回填产物 | **PASS**（`accounts_removed_are_backfilled_only=true`） |
| 旧表未被触碰 | **PASS**（admin 1 / teacher 2 / student 3 不变） |

**结论**：`--rollback` 的作用域是"所有被 `LegacyAccountLink` 引用的账号"，
不会删除无映射的账号（手工创建/后续新增）。

## 3. 幂等继续性

回滚后再次执行回填：

| 指标 | 值 |
|---|---|
| 二次回填退出码 | 0 |
| accounts / links / roles | 7 / 6 / 6（7 = 6 回填 + 1 预存） |
| 非 strict 一致性 | **PASS** |
| strict 差异 | 仅 `STRICT_COUNT_MISMATCH`，由预存账号解释（`accounts == links + 1`） |
| 预存账号 | 仍在 |

## 4. 事务边界说明

- 回填单行使用 `transaction.atomic()`，失败即回滚该行的所有写入；
- `--rollback` 亦在单事务内（先删 links，再删 accounts，级联删 Profile/Role）；
- 全部发生在**同一数据库连接**，不存在跨库补偿问题。

## 5. 未验证 / 限制

| 项 | 状态 | 说明 |
|---|---|---|
| 回滚后审计链完整性 | **NOT VERIFIED** | `AccountAuditLog` 中的 `backfill` 记录不会随回滚删除（历史留存），本轮未校验其一致性 |
| 部分回滚（按来源表） | NOT IMPLEMENTED | 当前只支持全量回滚 |
| 生产规模回滚耗时 | NOT RUN | 仅 6 行 |
| 回滚与并发写入竞争 | NOT RUN | 未做并发 |
