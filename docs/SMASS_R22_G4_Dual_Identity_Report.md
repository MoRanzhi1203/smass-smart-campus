# SMASS R2.2 G4 报告（双身份解析与路由策略）

- 阶段：G4（解决 L3 新旧身份兼容）
- 测试：`r22_account/tests/test_g4_dual_identity.py`（**12 例，全 PASS**）
- 解析器：`r22_account/identity.py`；路由策略：`r22_account/middleware.py`

## 1. 五类解析（唯一入口）

| kind | 条件 | 语义 |
|---|---|---|
| `legacy` | 仅 `session['info']` 合法 | 旧身份可用，但**不能**进 account 路由 |
| `account` | 仅有效 `Account` | 新身份可用，但**不能**进 legacy 路由 |
| `dual` | 两者都有 **且** `LegacyAccountLink` 匹配 | 允许两条路由 |
| `conflict` | 两者都有但 link 缺失/不匹配 | **一律拒绝** |
| `anonymous` | 都没有 | 拒绝 |

权威依据是 `LegacyAccountLink(source_table, source_pk)`，**不看**登录名、角色提示、数字主键巧合或客户端参数。

## 2. 关键安全规则：禁止"降级到更宽松的旧会话"

实测用例 `test_disabled_account_does_not_fall_back_to_legacy`：

```
Account 已停用 + session['info'] 仍有效
→ kind = conflict, reason = invalid_account_with_legacy
→ /legacy-parity/ 与 /r22/ 均 403
```

若不做这条限制，停用账号的用户可以靠旧 session 继续使用 legacy 路由——等于权限提升。

## 3. 路由策略

| 路由前缀 | 允许身份 |
|---|---|
| `/admin/`、`/student/`、`/teacher/`、`/legacy-parity/` | `legacy`、`dual` |
| `/r21/`、`/r22/` | `account`、`dual` |
| `/identity/` | 无策略（诊断端点，匿名可访问） |
| `/r21/login/`、`/r21/logout/`、`/r21/change-password/` | **策略豁免**（否则登录流程被自己挡住） |

不做"权限并集"：`dual` 只是允许两条路由，具体权限仍由 RBAC 判定。

## 4. 测试矩阵（12 例）

| # | 场景 | 断言 | 状态 |
|---|---|---|---|
| 1 | 仅 legacy | legacy 路由 200，account 路由 403 | PASS |
| 2 | 仅 account | account 路由 200，legacy 路由 403 | PASS |
| 3 | dual（link 匹配） | 两条路由均 200 | PASS |
| 4 | conflict（link 不匹配） | 两条均 403，`reason=link_mismatch` | PASS |
| 5 | anonymous | 两条均 403 | PASS |
| 6 | 停用 account + legacy | `conflict`，不降级 | PASS |
| 7 | 伪造 legacy（type=admin） | 仍是 legacy 身份，进不了 account 路由 | PASS |
| 8 | account 无 link + legacy | `conflict` | PASS |
| 9 | `route_policy_enabled=False` | 策略关闭，匿名字段也可达 | PASS |
| 10 | 角色撤销 | `has_perm` 立即为 False | PASS |
| 11 | 身份不授予权限 | account 身份 + 无角色 → 无 `view_data` | PASS |
| 12 | `identity_mode=account` | 忽略 legacy session，返回 `anonymous` | PASS |

## 5. 特性开关与回滚

| 开关 | 取值 | 作用 |
|---|---|---|
| `R22_FLAGS.identity_mode` | `off` / `account` / `dual` | 解析模式；`off` 即完全关闭 |
| `R22_FLAGS.route_policy_enabled` | bool | 是否启用路由策略 |
| `R22_FLAGS.audit_enabled` | bool | 是否写审计 |

回滚路径：
1. 把 `identity_mode` 设为 `off` → 身份解析全匿名（最小爆炸半径）；
2. 或从 `settings_r22.MIDDLEWARE` 移除两个中间件 → 回到纯 R2.1 行为；
3. 正式 `settings.py` 从未加载 → **正式系统零影响**。

## 6. 未做

| 项 | 状态 |
|---|---|
| 把路由策略应用到正式 `app01` 路由 | **NOT DONE**（正式路径未切换） |
| 浏览器 E2E（G7） | NOT STARTED（未授权） |
| 冲突事件的运营告警/看板 | NOT DONE |
| 双读期间的一致性抽检任务 | NOT DONE（G5/G6 范围） |

## 7. 结论

L3 已被"五类解析 + 拒绝降级 + 路由策略 + 特性开关"覆盖，且有 12 例实证。
但**没有**接入正式系统：`app01` 一行未改，正式配置不含这些中间件。
