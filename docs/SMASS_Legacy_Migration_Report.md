# app01 历史数据 → 统一模型的隔离迁移报告

> 脚本：`scripts/legacy_migration.py`
> 源库：`smass`（**只读**，26 表 / 111 列）
> 目标库：`smass_product_dev`（隔离副本）
> 日期：2026-10-31

---

## 1. 结论

| 检查 | 结果 |
|---|---|
| 正式库只读（迁移前后指纹） | **一致**：`940a687d84c8b8a35b7295a359aef18e160403ae25736d7844dbcb16d352455c` |
| 账号映射完整性 | 3 学生 + 2 教师 + 1 管理员，全部映射 |
| 角色归属 | 学生 `student`、教师 `teacher`、管理员 `system_admin` |
| 学籍归属 | 3 条 `StudentRecord`，班级为 `class` 类型组织单元 |
| 权限一致性 | 迁移学生/教师访问管理端 **403**；迁移管理员 **200** |
| 回滚 | 删除 3 学籍 / 6 账号 / 8 单元；回滚后重新迁移成功 |
| PII | 默认掩码（手机号掩码、身份证不迁移） |

证据文件：

```
.local/evidence/migration/preview.json
.local/evidence/migration/apply.json
.local/evidence/migration/verify.json
.local/evidence/migration/rollback.json
.local/evidence/migration/legacy_migration_manifest.json
```

---

## 2. 源数据实况（只读统计）

| 表 | 行数 | 迁移目标 |
|---|---|---|
| `app01_college` | 2 | 学院组织单元 |
| `app01_major` | 3 | 专业组织单元（上级=学院） |
| `app01_grade` | 3 | 年级单元（展示用，不改变班级单亲树） |
| `app01_classes` | 2 | 班级组织单元（上级=专业） |
| `app01_department` | 2 | 部门组织单元（团总支 / 学生会） |
| `app01_student` | 3 | 账号 + 学籍 + 学生角色 |
| `app01_teacher` | 2 | 账号 + 教师档案 + 教师角色 |
| `app01_admin` | 1 | 账号 + 系统管理员角色 |
| `app01_classcommittee` | 1 | 组织成员关系（班委） |
| `app01_leaguecadres` | 1 | 组织成员关系（团学干部） |
| `app01_student.password` | — | `pbkdf2_sha256$…`（直接继承） |
| `app01_admin.password` | — | `pbkdf2_sha256$…`（直接继承） |

---

## 3. 映射规则

### 3.1 组织

- 编码锚点：`LEGACY-COL-*`、`LEGACY-MAJ-*`、`LEGACY-GRD-*`、`LEGACY-CLS-*`、`LEGACY-DEPT-*`。
- **同名同类型同上级复用**：源数据中的"信息工程学院"与演示数据同名，
  迁移直接复用现有学院，不产生重复组织。
- 班级只挂一个上级（专业），年级作为独立单元展示，避免组织树出现双亲。

### 3.2 身份

| 字段 | 处理 |
|---|---|
| `login_name` | 学号 / 工号 / 管理员编号 |
| `display_name` | 源姓名 |
| `person_type` | `student` / `teacher` / `admin` |
| `password` | 直接继承 `pbkdf2_sha256` 哈希；非 Django 格式则设为不可用密码 |
| `must_change_password` | 继承失败时为 `True` |
| 角色 | `grant_role()` 授予，`AccountRole` 留痕 |
| 关联 | `LegacyAccountLink(source_table, source_pk, checksum)` |

### 3.3 业务

- `StudentProfile`：学号、姓名、学院名、班级名、掩码手机号。
- `StudentRecord`：`student_no`、姓名、`account`、`unit=班级`、
  `status=enrolled`、`extra`（性别/民族/政治面貌/寝室）。
- `TeacherProfile`：工号、姓名、掩码手机号。
- `OrganizationMembership`：
  - 教师 → 学院（`role=teacher`）
  - 班级辅导员 → 班级（`role=counselor`）
  - 班委 → 班级（`role=class_committee`）
  - 团学干部 → 部门（`role=league_cadre`）

### 3.4 敏感信息

| 字段 | 默认策略 | 显式授权后 |
|---|---|---|
| 手机号 | 掩码（前 3 + `****` + 后 4） | `SMASS_MIGRATE_REAL_PII=YES_I_HAVE_AUTHORIZATION` 时保留 |
| 身份证号 | **不迁移** | 同上，仅授权后 |
| QQ / 地址 | **不迁移** | — |
| 密码哈希 | 继承（不可逆） | — |

默认策略的原因：迁移验证的是"结构、映射、权限、回滚"，
不需要把真实 PII 复制进开发隔离库。

---

## 4. 幂等与回滚

### 4.1 幂等

- 已存在 `LegacyAccountLink` 的记录直接跳过。
- 账号已存在但缺链接时补建链接，不重复建号。
- 组织单元按编码锚点 + 同名复用双重判定。

实测：首次执行中途因字段长度失败；修复后**续跑**成功，
未产生重复账号（`links=6`，账号唯一）。

### 4.2 回滚

`--rollback` 执行顺序：

1. 删除迁移建立的 `StudentRecord`（按学号）；
2. 删除迁移账号及其 `StudentProfile` / `TeacherProfile` / `LegacyAccountLink` / 成员关系；
3. 删除 manifest 记录的成员关系；
4. 删除 `LEGACY-*` 前缀且无子节点、无成员、无学籍引用的组织单元。

复用单元（如"信息工程学院"）**不会被删除**，避免破坏演示组织树。

实测回滚：`records=3, accounts=6, memberships=0, units=8`；
回滚后重新 `--apply` 得到 `created_units=8, created_accounts=6, links=6`，
`--verify` 全部通过。

---

## 5. 权限一致性验证

`--verify` 会实际发起请求：

| 用例 | 期望 | 实测 |
|---|---|---|
| 迁移学生访问 `/admin/` | 403 | 403 |
| 迁移学生访问 `/student/` | 200 | 200 |
| 迁移教师访问 `/admin/` | 403 | 403 |
| 迁移管理员访问 `/admin/` | 200 | 200 |
| 每个迁移学生拥有 `student` 角色且关联学籍 | 是 | 是 |
| 每个迁移教师拥有 `teacher` 角色且关联档案 | 是 | 是 |
| 每个迁移管理员拥有 `system_admin` 角色 | 是 | 是 |
| `LEGACY-*` 组织编码无重复 | 是 | 是 |

---

## 6. 已知限制

1. 当前正式库历史数据量很小（3 学生 / 2 教师），迁移性能未做大样本压测；
   脚本按表分页读取即可扩展到万级（读源库为单表 `SELECT`）。
2. `app01` 的 `pinyin`、`qq`、`address`、`political` 仅部分迁移
   （`political` 进 `extra`，其余不迁移）。
3. 班级辅导员的"负责班级"语义映射为 `counselor` 组织关系；
   若未来引入专门的辅导员表，应改为迁移到新表并保留此关系作为兼容。
4. 迁移不改变正式库任何结构；正式库 `AUTH_USER_MODEL` 未被改写。
