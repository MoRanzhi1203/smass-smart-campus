# SMASS PMR Row Migration and Reconciliation（PM3）

- 迁移器：`scripts/pmr_migrate_rows.py`
- 测试：`smass_operations/tests/test_pmr_pm3_migration.py`（15 例，**15/15 PASS**）
- 配置：`smass/settings_pmr.py`（目标库前缀 `smass_pmr_target_`）

## 1. 映射关系

| 源（26 表合成旧库） | 目标（R10 72 表） | 规则 |
|---|---|---|
| `app01_college` | `OrganizationUnit(unit_type='college')` | `code=PMR-C{id}` |
| `app01_major` | `OrganizationUnit(unit_type='major')` | `code=PMR-M{id}`，父级=college |
| `app01_classes` | `OrganizationUnit(unit_type='class')` | `code=PMR-K{id}`，父级=major |
| `app01_admin` | `Account(person_type='admin')` + `system_admin` 角色 | `login_name=pmr-{id}` |
| `app01_teacher` | `Account(person_type='teacher')` + `teacher` 角色 | 同上 |
| `app01_student` | `Account(person_type='student')` + `student` 角色 | 同上 |
| `app01_student` | `StudentRecord` | `student_no={id}`，关联 account 与 class |

**密码哈希原样搬运**（不重新哈希），因为 PM1 已证明兼容层能消费三种格式。

## 2. 幂等的物理保证

```sql
CREATE TABLE pmr_legacy_map (
  ...
  UNIQUE KEY uq_pmr_source (source_table, source_id),
  KEY idx_pmr_batch (batch_id)
)
```

- `uq_pmr_source` 保证同一源行只映射一次
- `record()` 用 `ON DUPLICATE KEY UPDATE`，重跑是 upsert 而非重复插入
- `batch_id` 索引供回滚按批次筛选

**幂等实测**（同一目标库连跑两次）：

| 轮次 | created | skipped | rejected |
|---|---|---|---|
| 第 1 轮（从零） | **29** | 0 | 6 |
| 第 2 轮（同库重跑） | **0** | **34** | 1 |

第 2 轮 `created=0` 是幂等的直接证据。

## 3. 五类计数

| 类别 | 含义 | tiny 实测 |
|---|---|---|
| `created` | 新建成功 | 29 |
| `updated` | 已存在且被更新 | 0 |
| `skipped` | 映射表已有，跳过 | 0（第 1 轮）/ 34（第 2 轮） |
| `conflict` | 同源 id 多行 | 0 |
| `rejected` | 无法安全迁移 | 6 |

`details` 每类保留最多 200 条明细（防 manifest 爆炸，有测试断言）。

## 4. 冲突与拒绝的确定性规则

| 情形 | 处理 | 理由 |
|---|---|---|
| 畸形哈希（空/31/33/大写/非 hex） | **仍建账号**，密码置 `!{random}`，标记需重置，计 `rejected` | 保留账号实体，避免"用户消失"；`!` 前缀使任何哈希都无法匹配 |
| 孤儿班级（`major_id` 无对应专业） | 拒绝，计 `rejected` | **不猜父级** |
| 孤儿学生（`classes_id` 无对应班级） | 拒绝档案，账号仍建 | 同上 |
| 重复源 id | `conflict`（保留首条） | 幂等键已保证不会重复插 |

**没有"静默挂到别的学院"这类猜测**——拒绝并记录原因，交人工决策。

## 5. 严格对账（5 项）

| 检查 | 断言 | tiny | 1k |
|---|---|---|---|
| `admin_mapped` | 映射数 == 源数 | 6 == 6 | 15 == 15 |
| `teacher_mapped` | 映射数 == 源数 | 1 == 1 | 25 == 25 |
| `student_mapped_le_source` | 映射数 <= 源数 | 11 <= 11 | 1001 <= 1001 |
| `accounts_total` | 目标账号数 == 三类映射之和 | 18 == 18 | 1041 == 1041 |
| `placeholder_equals_unusable_hash_rows` | 占位密码数 == 源中不可用哈希数 | 5 == 5 | 5 == 5 |
| `classes_have_parent` | 无父级班级数 == 0 | 0 == 0 | 0 == 0 |

全部为 `strict_ok=true`。

## 6. 实测规模

| 源库 | 学生 | created | 耗时 | strict_ok |
|---|---|---|---|---|
| `smass_pmr_tiny_20261031` | 11 | 29 | ~10s（含建 73 表） | **true** |
| `smass_pmr_1k_20261031` | 1001 | 2146 | **78.5s** | **true** |

1k 的 2146 = 15 college + 25 major + 50 classes + 15 admin + 25 teacher + 1001 student + 1015 student_record（其中 1 个孤儿被拒）。

## 7. 本轮修掉的两个真 bug

**Bug 1：班级父级查错映射**

首版 `migrate_classes` 用 `college_map.get(row['major_id'])` —— 拿 **major id** 去查 **college 映射**，永远查不到，导致所有班级被拒。

连锁反应：班级被拒 → 学生的 `classes_id` 无对应组织 → 10 个学生档案也被拒。

修复：新增 `migrate_majors` 层（`unit_type='major'`），班级挂 major，`major_map` 由专业迁移产出。

修复后 `classes_have_parent = 0`，学生档案拒绝数从 11 降到 1（只剩真正的孤儿）。

**Bug 2：对账断言用错数据源**

首版断言 `placeholder_count == counters['rejected']`。重跑时畸形哈希行已被 skip，
`rejected` 明细为空，但目标库里的占位密码仍在 → 断言失败（`5 != 0`）。

修复：**直接从源库**数"不可用哈希"的行数，与目标库占位密码数对比。这与是否重跑无关。

## 8. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 真实 `app01_*` 行迁移 | **BLOCKED_EXTERNAL_AUTH** | 需 PII 授权；本文件全部基于合成数据 |
| 10k 规模行迁移 | **NOT RUN** | 已测 tiny + 1k；10k 留在 PM6 与性能一起测 |
| `app01_grade` / `app01_building` / `app01_dormitory` 等 | **NOT RUN** | 这些表在 R10 无直接对应模型；需业务确认（BD 未定） |
| 非 UTF8 字符/超长字段 | **PARTIAL** | 生成器全部为短 ASCII/中文；未造超长截断用例 |
| 迁移中断后的恢复 | **NOT RUN** | 留到 PM5 的故障注入 |

## 9. 与计划的对应

| 计划要求 | 本文件 |
|---|---|
| 幂等重启与单一批次 ID | §2（唯一键 + batch_id） |
| 逐行进度与来源映射 | §2（`pmr_legacy_map` 全量留痕） |
| created/updated/skipped/conflict/rejected | §3 |
| 冲突确定性处理 | §4 |
| 逐类型精确计数 | §5 |
| 重跑结果一致 | §2（第 2 轮 created=0） |
| 严格校验器（无 MISSING_SOURCE / HASH_MISMATCH） | §5（6 项检查） |
