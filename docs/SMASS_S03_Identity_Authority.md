# SMASS S03 — 统一身份权威（验证与加固）

状态：**`TESTED`** · 裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`
（正式认证切换 `AUTHENTICATION_SWITCH = NOT_AUTHORIZED`，见 §7）

---

## 1. 核查结论：能力已存在，本轮是"验证 + 显式验收"

按主任务书"do not rebuild already correct systems"，先做了实现核查。

**S03 的五条验收点在 `r22_account` 中已完整实现**：

| 验收点 | 实现位置 | 状态 |
|---|---|---|
| 身份解析唯一权威 | `r22_account/identity.py::resolve_identity` | 已实现 |
| 无 info-only 会话放行 | 同上，`_resolve_legacy` + `Identity.is_authenticated` | 已实现 |
| 冲突默认拒绝 | `KIND_CONFLICT` + `RoutePolicyMiddleware` | 已实现 |
| 账号绑定与可见性校验 | `LegacyAccountLink` + `_link_matches` | 已实现 |
| 不改正式认证配置 | `r22_account/conf.py`：正式 settings 不加载本 app | 已实现 |

既有测试覆盖：`test_g2_identity`（Account 契约）、`test_g4_dual_identity`
（路由策略/角色撤销/account-only）、`test_g7_browser`（三门户登录、停用与冲突）、
`test_g3_audit`（审计与脱敏）、`test_h4_alerts`（冲突告警）。

**本轮补的缺口**：缺少"以 S03 验收条款命名"的显式证据。
新增 `r22_account/tests/test_s03_identity_matrix.py`（23 例），逐条固化验收点。

## 2. 五类身份解析（唯一权威）

```python
Identity(kind, account, legacy, reason)
```

| kind | 含义 | `is_authenticated` |
|---|---|---|
| `legacy` | 仅旧身份（`session['info']` 合法，无 Account） | **False** |
| `account` | 仅新身份（Account 活跃） | True |
| `dual` | 两者都有且 `LegacyAccountLink` 匹配 | True |
| `conflict` | 两者都有但 link 缺失/不匹配 | **False** |
| `anonymous` | 都没有 | False |

关键设计：`legacy` 虽然是"合法旧身份"，但 `is_authenticated` 为 **False**——
这是"info-only 不得授予受保护访问"的直接体现。旧身份只用于
`legacy` 路由（`/admin/ /student/ /teacher/` 的旧业务页），不能进 account 路由。

## 3. Fail-closed 规则（最重要的安全性质）

`identity.py` 第 140-149 行：

```python
user_authenticated = bool(getattr(raw_user, 'is_authenticated', False))
if user_authenticated and account is None:
    if legacy is not None:
        return Identity(KIND_CONFLICT, None, legacy, reason='invalid_account_with_legacy')
    return Identity(KIND_ANONYMOUS, None, None, reason='invalid_account')
```

含义：**"Django 认为已登录"但"不是一个有效的 Account"**（停用账号、类型不符）
时，绝不退化成 legacy 身份。否则"账号被停用 + 残留旧 session"会成为提权后门。

`_normalize_legacy` 只接受 `id` / `type` / `name`，且 `type` 必须属于
`{admin, student, teacher}`；伪造 `type='superuser'` 或缺失 `id` 一律返回 `None`。

## 4. 路由策略

```python
ROUTE_POLICY = (
    ('/admin/',   ('legacy', 'dual')),
    ('/student/', ('legacy', 'dual')),
    ('/teacher/', ('legacy', 'dual')),
    ('/r21/',     ('account', 'dual')),
    ('/r22/',     ('account', 'dual')),
)
```

- `conflict` → 任何受限路由一律拒绝，并触发 `alerts.identity_conflict()`；
- `anonymous` → 拒绝并跳转登录；
- `legacy` 不能进 `account` 路由，`account` 不能进 `legacy` 路由（**不做权限并集**，
  避免"两套身份叠加放大权限"）。

豁免前缀 `POLICY_EXEMPT_PREFIXES` 含 `/r21/login/`、`/identity/` 等，
保证登录流程本身不被策略挡住。

## 5. 账号绑定：`LegacyAccountLink`

```python
def _link_matches(account, legacy):
    table = LEGACY_ROLE_TO_TABLE.get(legacy['type'])   # admin/teacher/student -> app01_*
    link = LegacyAccountLink.objects.filter(account=account).first()
    return link is not None and link.source_table == table and str(link.source_pk) == str(legacy['id'])
```

判定依据是**持久化的链接记录**，不是"登录名相同""数字主键巧合""角色提示相同"。
这是本模块最容易被写错的地方，所以用显式表 + 三要素比对。

## 6. 验收证据

### 6.1 新增 `r22_account/tests/test_s03_identity_matrix.py` — 23 例

| 类 | 例数 | 断言内容 |
|---|---|---|
| `IdentityResolutionMatrixTests` | 7 | 五类全矩阵：anonymous / legacy / account / dual / link 缺失 / link 指向他处 / link 表不符 |
| `FailClosedTests` | 4 | legacy 不算已认证；**停用 Account + 旧 session = conflict**；伪造 type；缺 id |
| `RoutePolicyEnforcementTests` | 5 | conflict 拒绝；legacy 进 `/r21/` 拒绝；account 进 `/admin/` 拒绝；匿名拒绝；`/identity/` 豁免 |
| `ModeOffTests` | 2 | `identity_mode=off` 时身份为 anonymous、不介入路由 |
| `AccountOnlyModeTests` | 2 | account 模式忽略旧身份、仍识别 Account |
| `FormalAuthConfigUntouchedTests` | 3 | `AUTH_USER_MODEL == auth.User`（Django 默认）；仅两个隔离实验配置允许覆盖；正式 settings 不含 r22 app 与中间件 |

运行命令：

```
python manage.py test r22_account.tests.test_s03_identity_matrix --settings=smass.settings_r22
```

### 6.2 既有实现回归

`r22_account` 套件（含上述新增）在 settings_r22 下运行，详见
`docs/dsh_run/SMART_CAMPUS_MASTER_STATE.json` 的 `regression` 段。

## 7. 与正式认证的关系（明确边界）

| 问题 | 结论 |
|---|---|
| 正式 `AUTH_USER_MODEL` 是否被改？ | **否**。实测为 Django 默认 `auth.User`（从未指向自定义用户模型）；`test_auth_user_model_is_django_default` 与 `test_no_settings_overrides_auth_user_model` 固化 |
| 正式 settings 是否加载 r22 身份层？ | **否**；`test_formal_settings_do_not_load_r22` 断言 |
| 正式认证是否已切换到统一 Account？ | **否**，`AUTHENTICATION_SWITCH = NOT_AUTHORIZED` |
| 未来能否在不改正式配置的前提下切到单一权威源？ | **能**：把 `R22_FLAGS['identity_mode']` 设为 `account` 即只认 Account；再逐步下线 legacy 路由即可，无需改动 `AUTH_USER_MODEL` |

## 8. 结论

- S03 的验收点全部**有实现、有测试、有显式证据**。
- 本轮未重写既有身份层，只补了验收条款级断言，并把"停用账号不得降级放行"
  这类隐含性质显式化。
- 正式认证切换仍未授权；本轮不触碰。
