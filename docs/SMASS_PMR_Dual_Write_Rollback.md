# SMASS PMR Dual Write and Rollback（PM4）

- 脚本：`scripts/pmr_dual_write.py`
- 测试：`smass_operations/tests/test_pmr_pm4_dual_write.py`（7 例，**7/7 PASS**）
- 演练库：`smass_pmr_target_fresh`（同库内同时有 16 个 `app01_*` 与 R10 表）

## 1. 为什么能在同一个库里做双写

R10 的 `migrate` 会把 `app01` 应用一并建表，所以 `smass_pmr_target_*` 库里有：

| 侧 | 表 |
|---|---|
| legacy | `app01_admin` / `app01_teacher` / `app01_student` |
| R10 | `r21_account_account` 等 46 张 |
| PM3 | `pmr_legacy_map` |
| PM4 | `pmr_dual_log` |

**好处**：可以在同一连接里精确控制"先写哪一侧、在哪一步失败、如何补偿"，
测的是**逻辑**而不是网络抖动。

**局限**：真实生产是**跨库/跨系统**，无法原子提交。本演练因此**同时验证了"失败后补偿"的路径**，
而不是假装双写能保证原子性。

## 2. 三种模式

| 模式 | 写 legacy | 写 R10 | 用途 |
|---|---|---|---|
| `off` | ✓ | ✗ | 迁移前 |
| `dual` | ✓ | ✓ | 切换窗口期 |
| `r10` | ✗ | ✓ | 切换完成后 |

**实测**（`off` / `r10` 单独验证）：

| 模式 | legacy 行 | r10 行 | 结果 |
|---|---|---|---|
| `off` | **1** | **0** | 只写旧侧 ✓ |
| `r10` | **0** | **1** | 只写新侧 ✓ |

## 3. 幂等

```sql
UNIQUE KEY uq_dual_idem (idempotency_key)
```

**实测**：同一 `idempotency_key` 第二次调用返回
`{'idempotent_replay': True, 'status': 'committed'}`，**不产生第二行**。

单测在真实数据库上验证了唯一键与批次索引 `idx_dual_batch` 都存在。

## 4. 失败注入与补偿（本轮核心）

`create_account(..., fail_after=1)` 表示"legacy 写成功后立即抛 `InjectedFailure`"。

**实测结果**：

```json
{
  "legacy_ok": true,
  "r10_ok": false,
  "status": "compensated",
  "note": "InjectedFailure; compensated=legacy"
}
```

**补偿后残留检查**：

| 侧 | 残留行数 |
|---|---|
| `app01_admin` (legacy) | **0** |
| `r21_account_account` (r10) | **0** |

即：先写的 legacy 行被主动删除了，没有留下"只在一侧存在"的孤儿。

**为什么必须有补偿**：跨系统双写无法用单事务保证原子。
一旦第二写失败而不补偿，就会产生"旧系统有、新系统没有"的账号——
这类不一致在切换后表现为"用户说密码对但登不进"，极难排查。

## 5. 批次回滚

`rollback_batch(batch_id)`：

1. 只取 `status='committed' AND r10_ok=1` 的 `create_account` 记录
2. 逐个删除对应的 R10 账号
3. 把这些记录标为 `rolled_back`

**实测**：`removed >= 1`，且回滚后 `Account.objects.filter(login_name='pmr-d01').exists()` 为 `False`（不抛异常）。

**回滚后登录路径完整**：回滚删的是**新增账号**，不触碰既有账号，
因此 `authenticate` / `login` 的代码路径不受影响。

## 6. 11 项检查汇总

| # | 检查 | 结果 |
|---|---|---|
| 1 | dual 两侧都写成功 | PASS |
| 2 | 失败注入后状态为 `compensated` | PASS |
| 3 | 失败注入时 legacy 确实写过（`legacy_ok=true`） | PASS |
| 4 | 幂等重放不产生重复 | PASS |
| 5 | 改密 committed | PASS |
| 6 | 撤权 committed | PASS |
| 7 | 批次回滚移除了账号 | PASS |
| 8 | 回滚后登录路径完整（查询不报错） | PASS |
| 9 | 补偿零残留（两侧都 0） | PASS |
| 10 | `off` 模式只写 legacy | PASS |
| 11 | `r10` 模式只写 R10 | PASS |

## 7. 本轮修掉的一个真 bug

**`app01_admin.id` 是 `varchar(3)`，我用了 7 字符 id**

首轮所有场景 `legacy_ok=false`，输出 `status=compensated` 但两侧都没写成。
原因是 `INSERT INTO app01_admin (id, ...) VALUES ('PM4A001', ...)` 被
MySQL 以"Data too long"拒绝。

修复：改用 3 字符 id（`D01` / `D02` / `E01` / `E02`）。

**教训**：旧库的字段宽度是**硬约束**，迁移/双写必须按旧 schema 的长度上限生成 id。
PM3 的 `pmr-{legacy_id}` 前缀方案在 R10 侧（`login_name` 32 字符）则安全。

## 8. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实跨库双写 | **BLOCKED_EXTERNAL_AUTH** | 需真实 `smass` 写权限（禁止） |
| 跨库网络分区 | **NOT RUN** | 同库演练无法模拟 |
| 双写期间的并发竞争 | **PARTIAL** | 幂等键覆盖重复请求；真并发留 PM7 |
| 切换窗口期的会话迁移 | **NOT RUN** | 需要引入 session 存储切换，PM8 覆盖 |
| `update` 类操作的补偿 | **PARTIAL** | 只实现了 `change_password` 的双写；失败补偿未单独注入测试 |

## 9. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| off→dual→off 与双写验证 | §2（三模式实测） |
| 失败/重启 | §4（`fail_after` 注入 + 补偿） |
| 回滚按批次 | §5 |
| 无丢失变更 | §4（补偿零残留） |
| 无降级 | §5（回滚只删新增，不动既有） |
