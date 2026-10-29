# SMASS S02 — 密码生命周期

状态：**`TESTED`** · 裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`
（**未对任何真实用户执行重置**；真实重置需数据所有者与安全双重授权，见 §8）

---

## 1. 现状核查：先复用，不重建

按主任务书"Implement or validate/reuse existing capabilities, do not rebuild already
correct systems"，先核查了既有实现：

| 既有能力 | 位置 | 结论 |
|---|---|---|
| `must_change_password` 字段 | `r21_account/models.py:104` | 新系统（统一 Account）已有 |
| `ForcePasswordChangeMiddleware` | `r21_account/middleware.py` | 依赖 `request.user`，**仅 r21/r22 settings 生效** |
| 临时口令 | `r21_account/services.py:195` `set_temporary_password` | 已实现 |
| 密码校验器 | `r21_account/services.py:185` / `app01/services/accounts.py:80` | 已实现 |
| 登录限速（按账号） | `r21_account/services.py` `LoginAttempt` | 新系统已有 |
| 登录限速（按 session） | `app01/services/accounts.py` `LOGIN_MAX_FAILURES=5` | 旧系统已有 |
| 审计 | `accounts.log_action` / `r21 audit()` | 已实现 |

**真实缺口**（本轮要解决的）：

1. 旧系统（`app01`，正式 `AUTH_USER_MODEL` 所在）走 **session** 而非 `request.user`，
   因此 `ForcePasswordChangeMiddleware` 在正式 settings 下**完全不生效**——旧系统
   没有任何强制改密能力。
2. 旧系统没有"会话失效"机制：管理员重置密码后，**旧会话仍然可用**。
3. 旧系统没有"仍持有历史 MD5"的状态登记，无法按策略筛选待重置账号。
4. 旧系统没有"停用账号"概念（`Admin/Student/Teacher` 三张表都没有 `is_active`）。

因此本轮在 **app01 侧补齐**，同时保持 r21/r22 既有实现不动（不重复造轮子）。

## 2. 数据设计：独立表，不改既有账号表

新增 `app01.AccountSecurityState`（表名 `app01_account_security_state`）：

| 字段 | 作用 |
|---|---|
| `account_type` + `account_id` | 复合定位三张既有账号表，**不 ALTER 既有表结构** |
| `must_change_password` | 强制改密标记 |
| `is_active` | 停用标记（停用即阻断登录与会话） |
| `legacy_hash_pending` | 是否仍持有 32 位历史 MD5 |
| `password_changed_at` | 最近改密时间（支撑 `MAX_AGE_DAYS`） |
| `temp_password_expires_at` | 一次性口令到期时间 |
| `session_epoch` | **会话世代**：重置/改密/停用时 +1，旧会话即刻失效 |
| `last_reset_by` | 最近重置操作者（审计辅助） |

唯一约束 `uniq_app01_account_security_state(account_type, account_id)`；
三个索引分别覆盖"待改密""遗留哈希""停用"三种筛选。

迁移文件：`app01/migrations/0005_accountsecuritystate.py`（**已生成但未对正式库执行**）。

## 3. 策略：可配置、默认全部关闭

`settings.PASSWORD_LIFECYCLE`：

```python
PASSWORD_LIFECYCLE = {
    'ENABLED': env_bool('SMASS_PASSWORD_LIFECYCLE', False),        # 总开关
    'FORCE_RESET_LEGACY': env_bool('SMASS_FORCE_RESET_LEGACY', False),
    'FORCE_RESET_INACTIVE': env_bool('SMASS_FORCE_RESET_INACTIVE', False),
    'MAX_AGE_DAYS': env_int('SMASS_PASSWORD_MAX_AGE_DAYS', 0),     # 0 = 不强制
    'TEMP_PASSWORD_TTL_MINUTES': env_int('SMASS_TEMP_PASSWORD_TTL_MINUTES', 1440),
    'DETECT_LEGACY_ON_LOGIN': env_bool('SMASS_DETECT_LEGACY_ON_LOGIN', True),
}
```

**全部默认关闭**，符合"策略可配置、默认 OFF"。学校密码政策未确认时，
系统行为与 S02 之前**完全一致**（中间件空操作、不拦截任何请求）。

## 4. 三项核心机制

### 4.1 会话世代（session epoch）——重置后旧会话立即失效

- 登录成功：`accounts.establish_session` 把当前 `session_epoch` 写进 session。
- 重置 / 改密 / 停用：`session_epoch += 1`。
- 每次请求：`PasswordLifecycleMiddleware` 比对 `session['sec_epoch']` 与状态行；
  不一致或无标记 → `session.flush()` + 拒绝（页面 302 到登录页，AJAX 401 JSON）。

改密成功后，服务层**主动把当前会话**写成新世代（`current_session[SESSION_EPOCH_KEY] = new_epoch`），
所以用户改完密码不会被自己的失效机制踢出，但**其它设备上的旧会话全部失效**。

### 4.2 强制改密拦截

`must_change_password=True` 时，除白名单（登录、登出、强制改密页、静态资源）外：
- 页面请求 → 302 到 `/account/password/forced/`
- AJAX / JSON → 403 `{"code": "must_change_password"}`

### 4.3 一次性临时口令

`POST /admin/admin/temp-password/`（管理员专用）：
- 生成随机口令 → 立刻用官方 PBKDF2 写入（**不留 MD5**）；
- 置 `must_change_password=True` + `temp_password_expires_at`；
- `session_epoch += 1`（踢掉该账号所有旧会话）；
- 明文只在响应 JSON 中出现**一次**，`Cache-Control: no-store`；
- 审计只写事件与 TTL，**不含明文**（有测试断言）。

## 5. 缺表降级（关键安全设计）

正式 `smass` 库保持只读、未应用 `0005` 迁移，因此状态表**不存在**。
服务层对此做了显式降级：

```python
def table_available(force=False):   # 探测失败即视为"策略未落地"
    ...

def get_state(...):        # 缺表 → None
def session_is_current(...):  # 缺表 → True（不改变既有行为）
def sweep(...):            # 缺表 → {'available': False, ...}
```

效果：**上了新代码但没迁库，不会 500，也不会悄悄改变登录/访问行为**。
策略真正生效的前提是"表存在 + `ENABLED=True`"，两者缺一不可。

## 6. 验收证据

### 6.1 新增专项测试 `app01/tests/test_s02_password_lifecycle.py` — 33 例

```
python manage.py test app01.tests.test_s02_password_lifecycle -v 1
Ran 33 tests in 22.360s
OK      exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `PolicyTests` | 3 | 默认全关；部分覆盖回落默认；默认不启用 |
| `TableAvailabilityTests` | 2 | 测试库有表；**模拟缺表时全部入口安全降级** |
| `TempPasswordIssueTests` | 8 | 标记强制改密；官方哈希；不存明文；到期；epoch+1；no-store；400/404/405；审计不含明文 |
| `TempPasswordPermissionTests` | 2 | 学生被拒且目标密码不变；匿名被拒 |
| `SessionEpochTests` | 6 | 缺状态=0；自增；世代匹配；无标记即拒；关闭时不拒；停用即失效 |
| `ForcedChangeFlowTests` | 7 | **完整浏览器旅程**：发临时口令→登录→被拦截→改密→恢复访问→新旧密码行为 |
| `EvaluateTests` | 4 | 默认不强制；遗留哈希按策略；停用标记；`MAX_AGE_DAYS` |
| `SweepTests` | 2 | dry-run 零写入；apply 只建状态、**绝不改密码** |

### 6.2 代表性完整旅程（`test_full_forced_change_journey`）

```
1. 管理员 POST /admin/admin/temp-password/  → 拿到一次性口令 temp
2. 学生用 temp 登录                           → 302 成功
3. GET /student/users/profile/                → 302 → /account/password/forced/
4. GET /account/password/forced/              → 200 含"修改密码"
5. POST 新密码                                → 302
6. state.must_change_password == False        → 标记清除
7. GET /student/users/profile/                → 200 恢复正常
8. verify_password(fresh, new) == True        → 新密码生效
9. verify_password(fresh, temp) == False      → 临时口令失效
```

### 6.3 未回归

```
python manage.py test app01                  → exit 0（含 S02 33 例）
python manage.py check --settings=smass.settings_r22  → 0 issues
python manage.py check --settings=smass.settings_r10  → 0 issues
```

全量回归结果见 `docs/dsh_run/SMART_CAMPUS_MASTER_STATE.json` 的 `regression` 段。

## 7. 审计与限速

| 事件 | 位置 | 载荷 |
|---|---|---|
| `password_reset_temp` | `accounts.log_action` | actor / target / ttl_minutes（**无明文**） |
| `password_change_lifecycle` | 同上 | actor / target / `self service` |
| `account_deactivated` / `account_reactivated` | 同上 | 原因（截断 64 字符） |
| `password_sweep` | `logger.info` | 账号类型 / 扫描数 / 遗留数 / dry_run |

限速沿用既有两层：旧系统 session 级（5 次/300 秒）、新系统 `LoginAttempt` 按账号。
本轮未新增第三套限速，避免策略分散。

## 8. 明确未做的事（需授权）

| 事项 | 状态 | 原因 |
|---|---|---|
| 对**真实用户**执行强制重置 | **未执行** | 需数据所有者 + 安全双重授权 |
| 对正式 `smass` 库应用 `0005` 迁移 | **未执行** | 正式库只读；需单独授权窗口 |
| 启用 `PASSWORD_LIFECYCLE` 全量策略 | **未启用** | 学校密码政策未确认（`BUSINESS_CONFIG_PENDING`） |
| 正式认证切换（旧系统→统一 Account） | **未执行** | `AUTHENTICATION_SWITCH = NOT_AUTHORIZED` |

`BUSINESS_CONFIG_PENDING`：`FORCE_RESET_LEGACY` / `FORCE_RESET_INACTIVE` /
`MAX_AGE_DAYS` 的**具体取值**取决于学校制度，代码已提供可配置点与安全默认。

## 9. 安全性声明

- 临时口令明文只在 HTTP 响应中出现一次，不入库、不入日志、不缓存。
- 所有密码写入只经 `accounts.set_password`（PBKDF2），不存在新的弱哈希路径。
- 未读取、未复制任何真实密码哈希；测试全部使用合成账号。
- 正式 `smass` 库：**0 写入**（26 表 / 111 列指纹未变）。
- `AUTH_USER_MODEL` 未修改：实测为 Django 默认的 `auth.User`（本项目任何正式
  settings 都未设置该键，`app01` 中也不存在 `UserInfo` 类）；既有三张账号表结构未变。
