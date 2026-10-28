# SMASS R2.2 G2 报告（身份契约与静态守卫）

- 阶段：G2（解决 L2 用户模型依赖）
- 测试：`r22_account/tests/test_g2_identity.py`（11 例）+ `test_g2_static_guard.py`（3 例）= **14 例，全 PASS**
- 隔离配置：`smass/settings_r22.py`，库 `smass_r22_proto`；正式 `settings.py` 不加载 `r22_account`

## 1. 身份依赖清单（G0 实测，`app01` 内）

| 模式 | 命中数 | 位置 |
|---|---|---|
| `get_user_model()` | **0** | — |
| `settings.AUTH_USER_MODEL` | **0** | — |
| `request.user` | **0** | — |
| `session['info']` / `session.get('info')` | 10 | `middleware/auth.py:44`、`utils/authz.py:35`、`views/teacher/te_basic.py:15`、`views/student/st_users_profile.py:22,48`、`views/student/st_classes_list.py:20`、`views/admin/ad_admin.py:96`、`services/accounts.py:347,364,385`、测试 3 处 |
| `is_staff` / `is_superuser` | 0 | — |
| `LogEntry` | 0 | — |

结论：`app01` **完全不依赖 Django 默认用户模型**，只用 `session['info']`。
L2 是"未来误引入"的风险，而不是现存缺陷——因此静态守卫可以要求**零违规**（无需白名单）。

## 2. `request.account` 契约

| 契约 | 实现 |
|---|---|
| 值必须是 `Account` 或 `None` | `request.account = SimpleLazyObject(lambda: identity.account)`；解析时用 `_unwrap()` 解包，保证是真实 `Account` |
| 不 monkeypatch `request.user` | 中间件只新增 `request.account` / `request.legacy_identity`，不改 `request.user` |
| 不把 `auth.User` 当 Account | `_resolve_account` 用 `isinstance(user, Account)` 严格判定，类型不符即 `None` |
| 旧身份单独暴露 | `request.legacy_identity`（规范化后的 `session['info']`，仅接受服务端写入的 `id/type/name`） |
| 每请求只解析一次 | `middleware` 内 `cache` 字典；实测 `spy.call_count == 1`（视图访问三个入口） |
| 未使用身份不查库 | 懒对象 + 缓存；`LegacyAccountLink` 仅在 dual 场景查询 |

## 3. 静态守卫

| 守卫 | 规则 | 结果 |
|---|---|---|
| 禁止 `get_user_model()` | AST 扫描 `app01` 全部 `.py` | 0 违规 |
| 禁止读 `settings.AUTH_USER_MODEL` | AST 扫描（属性 + 字符串字面量） | 0 违规 |
| 守卫自检 | 对含违规的样本代码断言能检出 | PASS（防"空转通过"） |

## 4. 测试矩阵（14 例）

| # | 场景 | 断言 | 状态 |
|---|---|---|---|
| 1 | 匿名 | `kind=anonymous`，`has_account=False` | PASS |
| 2 | 有效 Account | `kind=account`，`account_type=Account` | PASS |
| 3 | `request.user` 未被替换 | `isinstance(user, Account)` 且 pk 一致 | PASS |
| 4 | `account` 非 auth.User | `login_name` 正确、类型不是 User | PASS |
| 5 | 停用 Account | 降为 `anonymous`（fail closed） | PASS |
| 6 | 仅 legacy session | `kind=legacy`，`account=None` | PASS |
| 7 | 非法 legacy role | 视为匿名（不信任伪造 type） | PASS |
| 8 | 伪造 query 参数 | `?account=admin&role=admin` 不改变解析结果 | PASS |
| 9 | 请求级缓存 | `resolve_identity` 只调用 1 次 | PASS |
| 10 | `AUTH_USER_MODEL` 未变 | 仍为 `auth.User` | PASS |
| 11 | 开关 `identity_mode=off` | 全匿名且 reason=`mode_off` | PASS |
| 12-14 | 静态守卫 3 例 | 见 §3 | PASS |

## 5. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 懒对象被误当普通对象比较 | 解析时 `_unwrap()`；文档明确用 `isinstance`/`.pk` | 改回即时解析 |
| 非法 legacy session 被信任 | `_normalize_legacy` 白名单角色 + 必填 id | — |
| 守卫误报 | 仅扫描 `app01`，跳过 migrations/`__pycache__` | 调整扫描范围 |
| 正式行为受影响 | `settings.py` 不含该 app/中间件 | 不加载即无影响 |

## 6. 未做

| 项 | 状态 |
|---|---|
| 把 `app01` 视图改为使用 `request.account` | **NOT DONE**（正式路径未切换） |
| 浏览器级验证 G2 | 归入 G7（本轮未授权） |
