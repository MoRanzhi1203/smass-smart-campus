# SMASS R2.2 G8 切换与回滚演练证据

- 库：`smass_r22_g8_drill`（**全合成**，100 个 `G8S0000xx` 账号）
- 脚本：`scripts/r22_g8_drill.py`；配置：`smass/settings_r22_g8.py`
- 证据：`%TEMP%\smass_g8_drill\g8_drill.json`（**未进 Git**）
- 结果：**overall = PASS**

## 1. 演练步骤与实测

| # | 步骤 | 实测 |
|---|---|---|
| 1 | 合成种子 | 100 账号 + 100 映射 + 100 档案 + 100 角色 |
| 2 | 基线快照 | accounts=100, links=100, roles=100 |
| 3 | 切换前身份 | `off` 模式 → `anonymous` |
| 4 | 切换后五类 | account/legacy/dual/conflict/anonymous **全部匹配期望** |
| 5 | 切换后新建账号 | `G8N0000001` 创建成功（账号+档案+映射+角色） |
| 6 | 切换后改密 | `G8S000001` 密码变更成功 |
| 7 | 切换后授角色 | `G8S000001` 新增 `teacher`（原 `student` 保留） |
| 8 | 切换后停用 | `G8S000002` `is_active=False` |
| 9 | 故障注入 | 事务中途抛错 → `G8FAULT0001` **未持久化** |
| 10 | 回滚（dual→off） | 计数 101/101/102/101 完全保留 |
| 11 | 数据存活 | 新账号 ✓ 改密 ✓ 角色 ✓ 停用 ✓ |
| 12 | 权限提升检查 | conflict → 拒绝 |
| 13 | 批次审计 | chain_len=2、dry-run 批次已记录、unbatched_flag=false |

## 2. 关键断言（全部为 true）

```json
"counts_preserved": true,
"post_cutover_data_preserved": {
  "new_account_exists": true,
  "password_changed_survives": true,
  "role_survives": ["student","teacher"],
  "deactivated_survives": true
},
"fault_injection": {"account_persisted": false, "ok": true},
"privilege_escalation": {"conflict_kind": "conflict", "denied": true}
```

## 3. 演练中的真实修复

| # | 问题 | 修复 |
|---|---|---|
| 1 | `student_no` 超长（11 > 10） | 合成 ID 改为 `G8N0000001`（10 字符） |
| 2 | 重跑时 `Duplicate entry` | 脚本开头清理 `G8*` 合成账号（幂等） |
| 3 | 白名单不含 `smass_r22_g8_` | 扩展 allowlist（仍排除 `smass`） |

## 4. 局限

| 项 | 说明 |
|---|---|
| 规模 | 100 账号（非生产量级） |
| 无真实网络中断 | 故障注入用事务内抛错模拟，未模拟 MySQL 宕机 |
| 未模拟"切换期并发写" | 串行执行 |
| 未做反向同步 | 路径 A 下回滚不删数据，无需反向同步；但"新表独有数据"的处置未演练 |
