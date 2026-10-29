# SMASS S01 — 历史 MD5 密钥泄漏治理

状态：**`TESTED`** · 裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`
（真实数据重置与正式认证切换仍需独立授权，见 §7）

> 本文档**不复现**泄漏的密钥值。所有引用均为"历史 MD5 密钥字面量"的描述。

---

## 1. 问题

历史实现把 MD5 兼容校验用的密钥**硬编码在源码**里：

```python
LEGACY_MD5_SECRET_KEY = 'django-insecure-...'   # 66 字符，已随 Git 历史泄漏
```

该值同时是旧 `settings.SECRET_KEY`，因此它既是"历史密码哈希的盐"，
也曾经是"Django 会话/签名密钥"。删除一个字符串不能修复已泄漏的 Git 历史——
这正是 G0 必须做脱敏归档的原因。

## 2. 泄漏范围枚举（G0 实测，全可达历史）

工具：`<archive>\scan_history.py`；方法：`git cat-file --batch-all-objects`
遍历每个对象 + 每条 commit message + 每个标注标签正文。

```
objects          = {blob: 5446, commit: 87, tree: 656, tag: 1}
text blobs read  = 5390     bytes scanned = 37,588,434
commits scanned  = 87       refs scanned  = 10
```

含该字面量的 blob：**5 个**，分布在 **4 个路径**：

| 路径 | 性质 | 当前 HEAD 是否仍含 |
|---|---|---|
| `app01/services/accounts.py` | 常量定义（两个 blob 代次） | 是（本轮修复） |
| `docs/SMASS_PMR_Executive_Report.md` | 报告正文引用 | 是（本轮脱敏） |
| `scripts/pmr_synthetic_fixture.py` | 生成合成旧哈希的副本 | 是（本轮移除） |
| `smass/settings.py` | 历史硬编码 `SECRET_KEY` | 否（`06d210e` 已移入环境变量） |

历史来源：`git log --all -- smass/settings.py` → `4bddb70`（基线）、`06d210e`、
`3780591`、`94a1a96`。`06d210e` 是"统一密码链路"那次修复，把密钥改成读环境变量，
但**同时把同一值作为兼容常量搬进了 `accounts.py`**——所以泄漏面只是换了个位置。

## 3. 治理措施

### 3.1 密钥不再硬编码，改为受限来源注入 + 动态读取

`app01/services/accounts.py` 现在**不持有任何密钥字面量**：

```python
LEGACY_MD5_SECRET_KEY_ENV = 'SMASS_LEGACY_MD5_SECRET_KEY'
LEGACY_MD5_COMPAT_ENV     = 'SMASS_LEGACY_MD5_COMPAT'

def legacy_md5_secret():      # 每次调用读环境变量，未注入即空
    return (os.environ.get(LEGACY_MD5_SECRET_KEY_ENV) or '').strip()

def legacy_md5_compat_enabled():
    return (os.environ.get(LEGACY_MD5_COMPAT_ENV) or '').lower() in {'1','true','yes','on'}

def __getattr__(name):        # 让 accounts.LEGACY_MD5_SECRET_KEY 保持动态
    if name == 'LEGACY_MD5_SECRET_KEY':
        return legacy_md5_secret()
    raise AttributeError(...)
```

设计要点：

- **不设默认值**：`os.environ.get(...)` 只有一个参数，源码里不存在任何回退字面量。
- **不在 import 时固化**：用模块级 `__getattr__` 暴露 `LEGACY_MD5_SECRET_KEY`，
  这样既有调用点（`accounts.LEGACY_MD5_SECRET_KEY`）无需改动，
  但值始终反映"当前进程是否真的被授权注入"。
- **密钥不再等价于 Django SECRET_KEY**：两者彻底解耦。

### 3.2 历史 MD5 兼容默认关闭（安全默认）

```python
if is_legacy_hash(encoded):
    if not legacy_md5_compat_enabled():
        logger.warning('legacy_md5_rejected reason=compat_disabled object_id=%s', pk)
        return False
    if not legacy_md5_secret():
        logger.warning('legacy_md5_rejected reason=secret_not_injected object_id=%s', pk)
        return False
    ...  # 单次/双重 MD5 比对，命中后升级为 PBKDF2
```

后果（有意为之）：**没有显式迁移授权时，32 位 MD5 账号无法登录**。
这比"默认可登录"安全得多——泄漏的密钥不该继续充当隐形后门。
正式切换前必须按 §7 流程显式注入并开启，或直接执行强制重置。

### 3.3 低层工具 fail-fast

`legacy_md5()` 在无密钥时抛 `LegacyHashUnavailable`，而不是静默算出
一个"看起来像哈希"的值。生成器 `scripts/pmr_synthetic_fixture.py` 同样
改为无密钥即 `SystemExit`，避免用错密钥造出与真实数据不匹配的假 fixture。

### 3.4 文档脱敏

`docs/SMASS_PMR_Executive_Report.md` §3.1 的字面量已替换为
`<REDACTED — 该字面量已移除，改为环境变量注入>`，并补充治理说明。
原报告的其余事实（含"66 字符"的**长度**描述已改为不复述长度）保留。

### 3.5 测试基线同步

原先的 `KeyLeakRecordTests` 断言"密钥硬编码在源码中"——这是被本轮推翻的事实。
已改写为 `KeyLeakGovernanceTests`，断言**治理生效**：

- 源码中不得出现 `django-insecure-<20+>` 字面量；
- 密钥来自环境变量；
- 迁移开关默认关闭；
- 关闭时历史 MD5 登录被拒且不写库；
- 无密钥时抛 `LegacyHashUnavailable`；
- 状态摘要不含密钥。

测试用**合成测试密钥**注入（与真实值无关），因此测试本身不再是泄漏源。

## 4. 验收证据

### 4.1 新增专项测试 `app01/tests/test_s01_legacy_secret.py` — 16 例

```
python manage.py test app01.tests.test_s01_legacy_secret -v 2
Ran 16 tests in 0.730s
OK      exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `NoHardcodedSecretTests` | 4 | accounts.py / fixture 工具 / PMR 报告 无字面量；环境读取不得带默认值 |
| `SecureByDefaultTests` | 5 | 四种"密钥×开关"组合下 `available` 恒为假，除非两者齐备；默认拒绝且不写库 |
| `SecretNeverLeaksTests` | 4 | 拒绝日志、成功日志、异常文本、状态摘要均不含密钥；日志不含明文口令 |
| `SecretKeySeparationTests` | 3 | 历史密钥 ≠ `settings.SECRET_KEY`；不复用 settings；显式密钥与隐式密钥结果不同 |

### 4.2 受影响既有测试已适配并通过

```
python manage.py test app01.tests.test_high_risk app01.tests.test_auth
Ran 43 tests in 39.544s     OK      exit 0

python manage.py test smass_operations.tests.test_pmr_pm1_legacy_auth \
                    smass_operations.tests.test_pmr_pm2_fixture \
                    --settings=smass.settings_r10
Ran 53 tests in 8.564s      OK      exit 0
```

审计日志实测输出（证明拒绝路径被观测到）：

```
WARNING smass.audit: legacy_md5_rejected reason=compat_disabled object_id=1
WARNING smass.audit: legacy_md5_rejected reason=secret_not_injected object_id=1
```

### 4.3 运行时行为矩阵（实测）

| 密钥注入 | 迁移开关 | `available` | `legacy_md5()` | 历史 MD5 登录 |
|---|---|---|---|---|
| 否 | 否 | False | 抛 `LegacyHashUnavailable` | 拒绝（compat_disabled） |
| 是 | 否 | False | 可计算（低层工具） | 拒绝（compat_disabled） |
| 否 | 是 | False | 抛 `LegacyHashUnavailable` | 拒绝（secret_not_injected） |
| 是 | 是 | **True** | 可计算 | 允许，命中后升级 PBKDF2 |

`legacy_md5()` 只在密钥存在时可用（它需要密钥才谈得上"计算"）；
真正的授权边界在 `verify_password()`，要求**钥匙与开关同时具备**。

### 4.4 全量回归（实测，10 套件）

```
python scripts/r10_full_regression.py --json
TOTAL tests measured : 951
suites               : 10 (failed: 0)
all green            : True      exit 0
```

| 套件 | settings | 基线 | 现在 | 变化 |
|---|---|---|---|---|
| `smass_operations` | settings_r10 | 414 | **419** | +5（`KeyLeakGovernanceTests` 3→8） |
| `app01` | formal | 114 | **130** | +16（`test_s01_legacy_secret.py`） |
| `smass_analytics` | settings_r7 | 31 | 31 | — |
| `smass_organization` | settings_r4 | 69 | 69 | — |
| `smass_academic` | settings_r5 | 56 | 56 | — |
| `smass_workflow` | settings_r6 | 41 | 41 | — |
| `smass_api` | settings_r8 | 23 | 23 | — |
| `r22_account` | settings_r22 | 94 | 94 | — |
| `r21_account` | settings_r21 | 72 | 72 | — |
| `tests_e2e` | formal | 16 | 16 | — |
| **合计** | | **930** | **951** | **+21** |

期间还修复了回归脚本自身的一个缺陷：`scripts/r10_full_regression.py` 用
`subprocess(text=True)` 而未指定 `encoding`，在 Windows 上按 GBK 解码 UTF-8
子进程输出会抛 `UnicodeDecodeError`，导致统计为 0 并把通过的套件误报为失败。
已显式指定 `encoding='utf-8', errors='replace'`——这属于**测量工具的 bug**，
不是产品缺陷，单独记录以免混淆。

## 5. Django `SECRET_KEY` 复用与轮换（独立评估）

| 问题 | 结论 |
|---|---|
| 历史密钥是否仍是当前 `SECRET_KEY`？ | **否**。`06d210e` 起 `SECRET_KEY` 读 `DJANGO_SECRET_KEY` 环境变量，开发回退值是公开的 `django-insecure-dev-only-...`（已允许列表保留）。 |
| 两者是否共用存储？ | **否**。历史密钥读 `SMASS_LEGACY_MD5_SECRET_KEY`，`SECRET_KEY` 读 `DJANGO_SECRET_KEY`，断言 `test_django_secret_differs_from_legacy_secret` 固化。 |
| 历史 MD5 哈希能否被离线破解？ | **能**。MD5 无盐无迭代，密钥已在历史中公开 → 等价于已知盐。这是必须强制改密的根本原因。 |
| 当前会话/签名是否受影响？ | **未受影响**。因为 `SECRET_KEY` 早已与历史密钥分离；但历史数据里的 MD5 哈希仍可解。 |
| `SECRET_KEY` 是否需要轮换？ | 正式部署时必须使用独立生成的长随机值（`settings.py` 在 `DEBUG=False` 且缺失时直接启动失败，已强制）。轮换会导致现有会话失效——需在维护窗口执行，**本轮未做**（无生产授权）。 |

## 6. 残余风险

| 风险 | 说明 | 处置 |
|---|---|---|
| R1 历史 MD5 哈希仍可离线破解 | 密钥在 Git 历史中已公开，32 位 MD5 无盐 | S02 强制重置（需授权）；G0 已确保远端归档不含该值，新克隆者无法获得密钥 |
| R2 迁移期需短暂开启兼容 | 开启窗口内旧哈希仍可被消费 | 开启必须显式、限时、记录审计；建议改用"直接强制重置"避免开启 |
| R3 G0 之前的旧克隆副本 | 若存在他人的旧克隆，仍持有该密钥 | 只能通过全员改密消除；本轮无法回溯销毁 |
| R4 `legacy_md5()` 无开关限制 | 低层工具只要密钥在就可计算 | 有意如此（测试/迁移需要），授权边界放在 `verify_password()`，已有测试固化 |

## 7. 后续（需独立授权，不在本轮自动执行）

1. **强制重置**：对仍持有 32 位 MD5 的账号执行强制改密（S02 实现引擎，
   执行需数据所有者与安全双重授权）。
2. **正式认证切换**：必须在维护窗口内注入密钥或直接完成重置；
   `PRODUCTION_DEPLOYMENT = NOT_AUTHORIZED`。
3. **密钥轮换**：正式 `DJANGO_SECRET_KEY` 使用独立随机值并纳入轮换计划（S07）。

## 8. 安全性声明

- 本轮未读取、未复制任何真实密码哈希；所有测试用合成明文与合成密钥。
- 正式 `smass` 库：**0 写入**（26 表、111 列指纹见
  `docs/dsh_run/evidence/formal_db_after_regression.json`）。
- `AUTH_USER_MODEL` 未修改。
- 本文档、代码、测试与日志中均不含泄漏的密钥值。
