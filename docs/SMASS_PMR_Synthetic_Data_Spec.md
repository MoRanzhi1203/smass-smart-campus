# SMASS PMR Synthetic Data Spec（PM2）

- 生成器：`scripts/pmr_synthetic_fixture.py`
- 单元测试：`smass_operations/tests/test_pmr_pm2_fixture.py`（19 例，**19/19 PASS**）
- 库名前缀：`smass_pmr_`（强制，不匹配即拒绝）

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| 形状真实 | 从 `smass` **只导出结构**（`mysqldump --no-data`），零行复制 |
| 内容全合成 | 姓名/证件/手机由确定性生成器产出，格式**明显非真实** |
| 密码三态 | 单次 MD5 / 双重 MD5 / PBKDF2，现场用合成明文计算 |
| 对抗用例 | 空哈希、31/33 位、大写、非 hex、重复主键、孤儿外键 |
| 确定性 | 只用 `random.Random(seed)`，不碰全局 `random` |
| 可审计 | 输出 manifest（seed / 行数 / 格式分布 / 内容校验和） |

## 2. 无 PII 保证（可自动验证）

| 字段 | 合成格式 | 为什么安全 |
|---|---|---|
| 姓名 | `赵甲0042`（姓氏池 + 天干 + 序号） | 带序号后缀，可反查生成器 |
| 证件号 `cardID` | `SYNTH0000000000001` | **刻意不是** 18 位身份证格式 |
| 手机 `phone` | `00000000001` | 以 `000` 开头，真实号码不存在 |
| 地址 | `合成地址0001` | 含"合成"字样 |
| 密码明文 | `PmrSynth#000123` | 只用于算哈希，**不落库** |

生成器自校验（manifest 的 `verification` 段）：

```
non_synthetic_card  = 0   # SELECT COUNT(*) WHERE cardID NOT LIKE 'SYNTH%'
non_synthetic_phone = 0   # SELECT COUNT(*) WHERE phone NOT LIKE '000%'
```

任一项非 0 → `ok=false`，退出码 1。

## 3. 三种密码格式

| 格式 | 编码 | 权重 | 对应真实历史 |
|---|---|---|---|
| `legacy_md5_single` | `md5(key + raw)` | 50% | 正常旧数据 |
| `legacy_md5_double` | `md5(key + md5(key + raw))` | 20% | 旧 `save()` 重复哈希的坏数据 |
| `pbkdf2` | Django `pbkdf2_sha256$...` | 30% | 已升级的数据 |

权重之和经测试断言 `== 1.0`；500 次抽样覆盖全部三种。

## 4. 对抗用例

`ADVERSARIAL_CASES`（混入 `app01_admin`，不污染主计数）：

| label | 值 | 目的 |
|---|---|---|
| `empty_hash` | `''` | 空密码记录 |
| `short_hash` | `'a' * 31` | 少一位 |
| `long_hash` | `'a' * 33` | 多一位 |
| `uppercase_hash` | `'A' * 32` | 大写（正则只认小写） |
| `non_hex_hash` | `'z' * 32` | 非十六进制 |

另有两条**跨行**对抗：

| 用例 | 实现 | 预期 |
|---|---|---|
| 重复主键 | 尝试再插 `S000000000` | `duplicate_skipped=1` |
| 孤儿外键 | 插 `S999999999`，`classes_id=999999` | 孤儿引用存在 |

单测额外断言：除空串外，四种畸形哈希**都不被** `is_legacy_hash` 识别
（防止生成器与校验器对"什么算旧哈希"有分歧）。

## 5. 规模与实测

| 规模 | 目标行数 | 学生行 | 耗时 | content_checksum（前 16） |
|---|---|---|---|---|
| `tiny` | 10 | 11 | ~5s | `f3c2251c595db93e` |
| `medium` | 100 | 101 | **14.7s** | `edb7dfd91b8bbda6` |
| `1k` | 1 000 | 1 001 | **82.1s** | `ca285b8ad6842246` |
| `10k` | 10 000 | 10 001 | 见 PM6（单独测量） | 见 manifest |

学生行数 = 目标 + 1（孤儿用例）。

耗时主要来自 PBKDF2（30% 的行，Django 默认 720000 次迭代）。

## 6. manifest 结构

```json
{
  "database": "smass_pmr_1k_20261031",
  "scale": "1k",
  "seed": 20261031,
  "target_rows": 1000,
  "steps": [
    {"step": "dump_schema", "ok": true, "bytes": ...},
    {"step": "import_schema", "ok": true},
    {"step": "import_migrations", "ok": true},
    {"step": "populate_synthetic", "ok": true},
    {"step": "verify_no_pii", "ok": true, "bad_cards": 0, "bad_phones": 0}
  ],
  "stats": {"admin": ..., "student": 1001, "teacher": ..., "adversarial": 5,
            "orphan_reference": 1, "duplicate_attempted": 1, "duplicate_skipped": 1},
  "format_distribution": {"legacy_md5_single": ..., "legacy_md5_double": ..., "pbkdf2": ...},
  "content_checksum": "ca285b8a...",
  "verification": {"students": 1001, "non_synthetic_card": 0,
                   "non_synthetic_phone": 0, "migrations": 22},
  "ok": true,
  "note": "库不自动删除；清理需另行批准"
}
```

### 两个指纹（首版定义有缺陷，已修正）

**首版错误**：`content_checksum = sha256(id|encoded|format)`。
实测两次同 seed 得到**不同**值（`f3c2251c...` vs `f69a74f5...`）。

**根因**：PBKDF2 的 salt 是随机的，`encoded` 本身不可复现。
把 `encoded` 放进指纹，等于把随机性写进了"确定性校验和"。

**修正为两个指纹**：

| 字段 | 计算 | 性质 |
|---|---|---|
| `deterministic_checksum` | `sha256(id \| format \| raw_password)` | **完全可复现**（不含随机量） |
| `md5_encoded_checksum` | 仅 MD5 行的 `sha256(id \| encoded)` | 可复现（MD5 无 salt） |

PBKDF2 行的正确性不靠指纹验证，而靠 `check_password` 实测（见 PM3/PM5）。

**修正后实测**（同 seed 20261031，不同库名两次）：

```
smass_pmr_det_a_20261031  deterministic_checksum = 4ef2c4aba60a5ce0b2abf6b8f9ccde5e...
smass_pmr_det_b_20261031  deterministic_checksum = 4ef2c4aba60a5ce0b2abf6b8f9ccde5e...
                                                      ^^^ 完全一致
```

## 7. 迁移记录的处理（继承 H5 教训）

结构复制后**额外** dump `django_migrations` 的**数据**（22 行）：

```bash
mysqldump --no-create-info smass django_migrations
```

否则 Django 认为所有迁移未应用，`migrate` 会撞
`(1050) Table 'django_content_type' already exists`（HD-009）。

该表只含 app 名 + 迁移名 + 时间，**无 PII**。

## 8. 安全守卫

| 守卫 | 行为 |
|---|---|
| 库名前缀 | 非 `smass_pmr_` → `SystemExit` |
| 库已存在 | 拒绝，不覆盖 |
| 源库 | 只 `--no-data` 读取结构 |
| 清理 | 见 PMD-006：仅限本任务创建 + 零业务数据 + 记录到命令日志 |

## 9. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实数据分布特征 | **BLOCKED_EXTERNAL_AUTH** | 需要真实数据的统计特征（如姓名长度分布、重复率） |
| 真实的 fk 断裂模式 | **PARTIAL** | 只造了 1 条孤儿；真实库可能有多模式 |
| 10k 以上规模 | **NOT RUN** | 10k 已达 PBKDF2 耗时瓶颈；更大规模见 PM6 |
| 并发写入下的生成器 | **N/A** | 生成器是单线程离线工具 |

## 10. 与计划的对应

| 计划要求 | 实现 |
|---|---|
| 合成但 schema 兼容且可复现 | §1 §5 §6（seed + checksum） |
| 含真实数据中的对抗模式 | §4 |
| 无 PII 或生产哈希 | §2（两个 SQL 自校验） |
| 记录 seed、标记、行数、校验和、格式映射 | §6 |
| 生成/清理均在批准隔离中 | §8 + PMD-006 |
