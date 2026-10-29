# SMASS PMR Legacy Auth Compatibility（PM1）

- 测试：`smass_operations/tests/test_pmr_pm1_legacy_auth.py`（29 例）
- 结果：**29/29 PASS**
- 全部使用**合成密码**，未读取任何真实哈希

## 1. 格式映射表（有源码依据，不猜测）

| 项 | 值 | 源码位置 |
|---|---|---|
| 旧哈希算法 | MD5 | `app01/utils/encrypt.py::md5` |
| 输入构造 | `md5(KEY + raw)`，即 `hashlib.md5(key.encode()).update(raw.encode())` | 同上 |
| 旧密钥 | `LEGACY_MD5_SECRET_KEY`（66 字符，`django-insecure-` 前缀） | `app01/services/accounts.py:32` |
| 识别规则 | `^[0-9a-f]{32}$`（**只认小写**） | `accounts.py:63` |
| 单次哈希 | `md5(secret + raw)` | `accounts.py::legacy_md5` |
| **双重哈希** | `md5(secret + md5(secret + raw))` | `accounts.py::verify_password` 的第二个分支 |
| 比较方式 | `secrets.compare_digest`（常量时间） | `accounts.py` |
| 官方哈希 | Django `make_password`（PBKDF2-SHA256） | `accounts.py:set_password` |
| 升级时机 | 校验成功后**懒惰升级**，不批量重写 | `_upgrade_to_official_hash` |

**双重哈希的成因**（源码注释说明）：早期 `Admin`/`Student`/`Teacher` 的
`save()` **无条件**调用 `md5(SECRET_KEY + raw)`，而 `clean_password` 又先 md5 一次，
导致同一明文在不同路径下被哈希 0~2 次。

## 2. 验证结果

### 2.1 格式识别

| 测试 | 断言 |
|---|---|
| `test_32_hex_is_legacy` | 32 位小写 hex → True |
| `test_uppercase_hex_not_matched` | 大写 32 位 → **False**（避免误升级） |
| `test_django_hash_not_legacy` | PBKDF2 → False，且 `is_preferred_hash` True |
| `test_short_or_long_hex_not_legacy` | 31 / 33 位 → False |
| `test_non_hex_not_legacy` | 32 个 `z` → False |
| `test_none_not_legacy` | `None` → False（不崩） |

### 2.2 等价性（交叉验证）

用**独立实现**的 `synth_md5` 与服务层 `legacy_md5` / `utils.md5` 三者互验：

- `test_service_matches_independent`
- `test_util_matches_independent`
- `test_secret_affects_hash`（换密钥必须换结果）

### 2.3 兼容与升级

| 测试 | 行为 |
|---|---|
| `test_single_md5_accepted` | 单次 MD5 正确密码 → 通过 |
| `test_single_md5_upgraded_on_success` | 通过后 `password` 变为 PBKDF2，且 `save(update_fields=('password',))` |
| `test_double_md5_accepted` | 双重 MD5 → 通过 |
| `test_double_md5_also_upgraded` | 双重 MD5 也升级 |
| `test_upgraded_hash_accepts_same_password` | 升级后同密码仍可登录 |
| `test_upgraded_hash_rejects_old_md5_reuse` | 升级后把旧 MD5 当密码传入 → **拒绝** |

### 2.4 拒绝路径

| 测试 | 行为 |
|---|---|
| `test_wrong_password_rejected` | 拒绝，**且不改动存储**（`saved == []`） |
| `test_empty_password_rejected` | 空密码 / `None` 拒绝 |
| `test_empty_stored_hash_rejected` | 存储为空 → 拒绝 |
| `test_unknown_format_rejected_not_crash` | 非法编码 → 返回 False，**不抛异常** |

### 2.5 官方哈希

| 测试 | 行为 |
|---|---|
| `test_pbkdf2_accepted` / `_wrong_rejected` | 正常 |
| `test_set_password_writes_official_hash` | 写入 PBKDF2，**存储中无明文** |
| `test_set_password_empty_rejected` | 空密码抛 `PasswordError` |

### 2.6 限速

| 测试 | 行为 |
|---|---|
| `test_limits_defined` | 5 次 / 300 秒 |
| `test_session_lock_and_unlock` | 达阈值后锁定，清除后解锁 |

## 3. 密钥泄漏风险（记录事实）

`LEGACY_MD5_SECRET_KEY` **硬编码在源码中**，且带 `django-insecure-` 前缀
（Django 自动生成时使用的前缀），说明它曾是某个开发环境的 `SECRET_KEY`。

三个断言把它固化为事实：

```python
test_legacy_key_is_hardcoded_in_source      # 密钥存在且符合结构特征
test_legacy_key_differs_from_current_secret # 与当前 SECRET_KEY 不同
test_key_present_in_repo_source             # 确实在仓库文件里
```

**风险影响**：

| 项 | 评估 |
|---|---|
| 旧 MD5 可否离线破解 | **可以**（密钥已知 + MD5 无盐 + 无迭代） |
| 谁能利用 | 任何拿到本仓库的人 |
| 缓解 | 只在**校验**时用；命中即升级；不导出哈希 |
| 残余风险 | 升级窗口期内，若哈希泄漏仍可被解开 |
| 建议 | 生产切换后**强制全员改密**，或对未登录账号做一次性重置 |

**这不阻断合成迁移**，但必须写进授权包（PM9）与 GO/NO-GO（PM10）。

## 4. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实旧库哈希命中率 | **BLOCKED_EXTERNAL_AUTH** | 需读取 `app01_*` 真实哈希（PII） |
| 旧密钥是否与某环境 `SECRET_KEY` 完全一致 | **NOT RUN** | 需该环境配置；不影响兼容逻辑 |
| `app01` 层"停用账号" | **N/A** | `Admin`/`Student`/`Teacher` **没有 `is_active` 字段**（源码确认）。停用机制在 R21 `Account.is_active` 层，已由 H1 测试覆盖 |
| 登录限速的端到端集成 | **PARTIAL** | 本文件验证 Session 计数与锁定/解锁；真实 HTTP 限速在 PM8 覆盖 |
| 哈希强度升级（PBKDF2 迭代数） | **PARTIAL** | 用 Django 默认；未自定义迭代数 |

## 5. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 逐模型字段与哈希格式有源码依据 | §1 |
| 用合成样本喂真实校验路径，含错误密码/未知格式/停用/限速 | §2 |
| 不是假登录或绕过认证 | §2.3 / §2.5 全走真实 `verify_password` |
| 明确升级策略（懒惰 vs 批量） | §1（懒惰升级） |
| 回滚策略（切回旧哈希不可行） | §3（建议强制改密而非回滚） |
| 不声称"迁移后密码兼容" | §4（真实库命中率 BLOCKED_EXTERNAL_AUTH） |
