# SMASS R2.2 G5 一致性报告（Consistency Report）

- 校验器：`r21_account/management/commands/verify_account_consistency.py`
- 模式：**check-only**（默认）/ `--json` / `--plan-only`；**没有任何 apply/repair 选项**
- 白名单：`smass_r21_`、`smass_r22_g5_`、`test_smass_`（`smass` 被拒）

## 1. 检查项与差异码

| 差异码 | 级别 | 含义 |
|---|---|---|
| `STRICT_COUNT_MISMATCH` | critical | 账号总数 ≠ 旧表行数（仅 `--strict-count`） |
| `LINK_ACCOUNT_MISMATCH` | critical | 映射数**多于**账号数（异常） |
| `MISSING_SOURCE` | critical | 映射指向的旧表行不存在 |
| `HASH_MISMATCH` | critical | 新表哈希 ≠ 旧表哈希（疑似二次加密） |
| `ROLE_MISMATCH` | high | 角色与 `person_type` 不符 |
| `STATUS_INCONSISTENT` | high | `is_active=True` 却有 `deactivated_at` |
| `UNLINKED_ACCOUNT` | high | 账号的 login_name 在旧表存在但缺映射 |
| `ORPHAN_PROFILE` | medium | 档案的 account 没有映射 |
| `DANGLING_LINK` | critical | 映射指向不存在的 Account（防御性） |

## 2. 演练中的一次真实缺陷修复

初版校验器用 `link_total != account_total` 判断，导致：

```
二次回填后：accounts=7, links=6 → 误报 LINK_ACCOUNT_MISMATCH
```

根因：**"账号多于映射"是正常现象**（管理员手工创建、非回填来源的账号）。修正为：

- `LINK_ACCOUNT_MISMATCH` 只在 `links > accounts` 时触发；
- 新增 `UNLINKED_ACCOUNT`：仅当该账号的 `login_name` **确实存在于对应旧表**时才报错。

这样既不会漏报"回填遗漏"，也不会把合法账号误报为不一致。

## 3. 差异注入与检出（stage 库，注入后均恢复）

| 注入 | 期望检出 | 实际 | 是否自动修复 |
|---|---|---|---|
| 删除 1 条 `LegacyAccountLink` | `ORPHAN_PROFILE` + `UNLINKED_ACCOUNT` | 两者均检出 | **否**（`repair_executed=false`） |
| 撤销 1 个角色 | `ROLE_MISMATCH` | 检出 | 否 |
| 制造状态矛盾（`is_active=True` + `deactivated_at`） | `STATUS_INCONSISTENT` | 检出 | 否 |

注入后恢复 → 校验回到 `ok=true`，计数与 pristine 完全一致。

## 4. 机器可读输出示例（脱敏）

```json
{"ok": true, "database": "smass_r22_g5_stage",
 "counts": {"legacy_rows": 6, "accounts": 6, "links": 6,
            "student_profiles": 3, "teacher_profiles": 2},
 "issues": [], "mode": "check-only", "repair_executed": false}
```

异常时 `issues[]` 每项含 `code` / `severity` / `count` / `samples`（最多 5 条，仅 login_name 或 `table:pk`）/ `plan`。

## 5. `--plan-only`

只输出修复计划文本，**不执行任何写操作**（如 `HASH_MISMATCH` → "确认是否被二次加密，禁止自动重写哈希"）。

## 6. 未做

| 项 | 状态 |
|---|---|
| 自动修复 | **刻意不做**（歧义冲突必须人工评审） |
| 定时一致性巡检 | NOT DONE（G6+） |
| 差异告警推送 | NOT DONE |
