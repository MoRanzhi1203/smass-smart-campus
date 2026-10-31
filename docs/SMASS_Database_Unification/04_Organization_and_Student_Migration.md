# 04 组织与学籍迁移

> 源：`app01_college/major/grade/classes/department/classcommittee/leaguecadres`
> 目标：`OrganizationUnit`、`OrganizationMembership`、`StudentRecord`
> 演练库：`smass_unified_verify`

---

## 1. 组织树映射

| 源表 | 目标 | 编码锚点 | 上级 |
|---|---|---|---|
| `app01_college` | `OrganizationUnit(college)` | `LEGACY-COL-{id}` | 根 |
| `app01_major` | `OrganizationUnit(major)` | `LEGACY-MAJ-{id}` | 学院 |
| `app01_grade` | `OrganizationUnit(grade)` | `LEGACY-GRD-{id}` | 学院（展示用） |
| `app01_classes` | `OrganizationUnit(class)` | `LEGACY-CLS-{id}` | 专业 |
| `app01_department` | `OrganizationUnit(department)` | `LEGACY-DEPT-{id}` | 根 |

**设计要点**：

- 班级**只挂专业**（单亲树），年级不成为班级的第二上级；
  年级单元保留用于展示与入学年份推断。
- 同名同类型同上级的单元**复用**（如源"信息工程学院"与验证库的
  "统一验证学院"不同名时新建；若与已有同名学院则复用），避免重复组织。
- 组织编码以 `LEGACY-` 为前缀，便于回滚与识别；复用单元不删除。

**实测**：12 个组织单元（学院 2 + 专业 3 + 年级 3 + 班级 2 + 部门 2），
`units_legacy=12`，与源表行数之和一致。

---

## 2. 班级与辅导员

| 源字段 | 目标 | 说明 |
|---|---|---|
| `classes.name` | `OrganizationUnit.name` | |
| `classes.major_id` | `unit.parent` | 专业 |
| `classes.counsellor_id` | `OrganizationMembership(account=教师, unit=班级, role='counselor')` | 每个班级一条 |

实测：2 个班级 → 2 条 counselor 关系（另有班委/团学各 1 条，共 4 条任职）。

---

## 3. 学籍

| 源字段 | 目标 | 处理 |
|---|---|---|
| `student.id` | `StudentRecord.student_no` | 唯一 |
| `student.name` | `StudentRecord.name` | |
| `classes_id` | `StudentRecord.unit` | 班级 |
| `building/dormitory` | `extra.dormitory` | 实测为空 |
| `sex/nation/political` | `extra.*` | 保留原值（未做字典翻译） |
| 入学日期 | `StudentRecord.enrolled_at` | 由年级名推断（`2021级` → `2021-09-01`）；无年级则迁移日 |
| 学籍状态 | `status='enrolled'` | 源无状态字段 |

**为什么用年级推断入学日期**：源库没有入学日期字段；用班级所属年级
（如 2021 级）推断比"迁移当天"更接近事实，且可审计。
若年级缺失，退化为 `date.today()` 并在文档标注。

实测：3 条学籍，学号 2021000001/2021000002/2022000001，
入学日期 2021-09-01/2021-09-01/2022-09-01。

---

## 4. 班委与团学干部

| 源表 | 目标 | role |
|---|---|---|
| `app01_classcommittee` | `OrganizationMembership(unit=班级)` | `class_committee` |
| `app01_leaguecadres` | `OrganizationMembership(unit=部门)` | `league_cadre` |

**语义说明**：新模型没有独立的"班委/团学"表，用组织成员关系的 `role`
字符串表达；具体职务名称（源表的 `committee`/`duties` 枚举）**未迁移**
（新模型无字段），这也是 `app01_position` 归为 ARCHIVE_ONLY、
`app01_teacherposition` 归为 UNRESOLVED 的原因。

若后续需要在产品展示具体职务，应新增任职表并回填。

---

## 5. 对账（实测）

| 检查 | 源 | 目标 | 结果 |
|---|---|---|---|
| 学院 | 2 | 2（LEGACY-COL） | PASS |
| 专业 | 3 | 3 | PASS |
| 年级 | 3 | 3 | PASS |
| 班级 | 2 | 2 | PASS |
| 部门 | 2 | 2 | PASS |
| 组织合计 | 12 | 12 | PASS |
| 学籍 | 3 | 3 | PASS |
| 任职关系 | 4（2 辅导员 + 1 班委 + 1 团学） | 4 | PASS |
| 学生档案 | 3 | 3 | PASS |
| 教师档案 | 2 | 2 | PASS |
| 住宿 | 0（源字段为空） | 0 | PASS |

证据：`.local/evidence/unify/reconcile.json`。

---

## 6. 组织与学籍的运行时依赖

- 产品页面只读 `OrganizationUnit` / `StudentRecord`；
- `StudentProfile.college_name/classes_name` 是快照，用于用户范围匹配
  （学院管理员的 `scope_college`）；
- 旧组织表不再被产品读取（依赖扫描 0 运行时引用）；
- 迁移复用既有同名单元时，不删除、不覆盖。

---

## 7. 未覆盖/待确认

| 项 | 说明 |
|---|---|
| 年级与班级的双重归属 | 单亲树只保留专业归属；年级仅展示 |
| 辅导员与班主任区分 | 源只有 `counsellor`，统一映射为 counselor；无独立"班主任"角色 |
| 学院编码 | 源用自增 id，新库用 `LEGACY-COL-*`；如需与学校编码对齐，应单独映射表 |
| 组织有效期 | 源无起止日期，迁移未设置 `valid_from/to` |
