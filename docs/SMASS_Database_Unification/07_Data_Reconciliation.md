# 07 数据对账

> 源：`smass`（只读）；目标：`smass_unified_verify`（迁移批次）
> 脚本：`scripts/db_unify_reconcile.py`
> 证据：`.local/evidence/unify/reconcile.json`、`migration_apply.json`

---

## 1. 七类迁移民统计（实测）

| 类别 | 数量 | 明细 |
|---|---|---|
| MIGRATE / 迁入 | 6 账号 | 学生 3、教师 2、管理员 1 |
| TRANSFORM / 转换 | 5 | 手机号掩码 5 条；入学日期按年级推断 3 条 |
| MERGE / 去重合并 | 0 | 本次数据无重复；重复执行时复用计数 |
| REGENERATE / 重建 | 10 表 | auth_* / django_* 由迁移图重建 |
| ARCHIVE_ONLY / 仅归档 | 1 表 | `app01_position`（4 行教师职务字典） |
| DISCARD_CANDIDATE / 舍弃候选 | 2 表 + 敏感字段 | `django_admin_log`、`django_session`；身份证号 |
| UNRESOLVED / 未解决 | 1 表 | `app01_teacherposition`（2 行，语义不明） |
| 校验失败 | 0 | `verify_failures=0` |

> 另：4 张空表（building/dormitory/dormitorynumber/nation）标记为 REGENERATE，
> 不计入迁入。

---

## 2. 对账明细（源 vs 目标）

| 检查 | 源 | 目标 | 结果 |
|---|---|---|---|
| 学生账号 | 3 | 3（link `app01_student`） | PASS |
| 教师账号 | 2 | 2 | PASS |
| 管理员账号 | 1 | 1 | PASS |
| 学籍数量 | 3 | 3 | PASS |
| 学生档案 | 3 | 3 | PASS |
| 教师档案 | 2 | 2 | PASS |
| 组织单元 | 12 | 12 | PASS |
| 组织任职关系 | 4 | 4 | PASS |
| 住宿数据 | 0 | 0 | PASS |
| 历史密码继承（学生） | 3 PBKDF2 | 3 可登录 | PASS |
| 教师密码继承 | 2 PBKDF2 | 2 | PASS |
| PII 掩码（手机号） | — | 5 条掩码 | PASS |
| 身份证迁移 | — | 0 条 | PASS（按策略不迁） |

补充核对：

| 项 | 结果 |
|---|---|
| `LegacyAccountLink` 总数 | 6（每账号一条） |
| 重复登录名 | 0 |
| 重复学号 | 0 |
| 孤儿学籍（无账号） | 0 |
| 组织编码重复 | 0 |
| 班级上级类型 | 全部为 `major` |
| 辅导员关系 | 2 个班级各 1 条 |
| 班委/团学 | 各 1 条 |

---

## 3. 差异与解释

| 项 | 现象 | 解释 |
|---|---|---|
| 住宿 | 源 0 / 目标 0 | 正式库 `app01_student.building/dormitory` 全为空；非迁移丢失 |
| 组织单元 | 12 = 2+3+3+2+2 | 学院/专业/年级/班级/部门全量迁移 |
| 任职 4 | 2 辅导员 + 1 班委 + 1 团学 | 与源表行数一致 |
| 教师职务 | 未迁移 | `teacherposition` 语义不明，进入 UNRESOLVED |
| 民族/职务字典 | 未迁移 | 空表/无消费方 |
| 身份证 | 不迁移 | 敏感 PII 策略 |

---

## 4. 被拒绝与未解决（必须人工处理）

| 项 | 数量 | 原因 | 建议 |
|---|---|---|---|
| `app01_teacherposition` | 2 行 | 新模型无教师职务字段；无法确定是否等同职称/任职 | 由数据所有者确认后：新增职称字段或并入任职表 |
| `app01_position` | 4 行 | 字典表；新模型无对应 | 归档；排课职称仅影响周课时上限 |
| 身份证号 | 5 行（3 学生+2 教师） | 敏感 | 保留在正式库；新库不迁 |
| 出生日期/民族编码 | 部分 | 字段语义未确认 | 保持 `extra` 原值，不做翻译 |

**本轮未对上述项执行 DELETE**；正式库原样保留。

---

## 5. 一致性校验建议（已提供/可扩展）

| 检查 | 当前状态 |
|---|---|
| 账号唯一、学号唯一 | `db_unify.py verify` 已覆盖 |
| 档案 1:1 | verify 已覆盖 |
| 角色组存在 | verify 已覆盖 |
| 学号 Record↔Profile 一致 | 迁移同时写；建议纳入 verify（后续） |
| 组织树类型合法 | 服务层 `validate_parent` 保证 |
| 任职 role 白名单 | 当前字符串，建议校验集合 |

---

## 6. 证据索引

| 文件 | 内容 |
|---|---|
| `migration_apply.json` | 迁入数量 + 七类统计 + 源指纹 |
| `migration_verify.json` | 角色/学籍/权限一致性 |
| `reconcile.json` | 源/目标对账 13 项 |
| `rollback.json` | 回滚删除数量 |
| `reapply.json` / `reverify.json` | 回滚后重迁与再校验 |
| `detached.json` | 断库运行结果 |
| `verify.json` / `init.json` / `seed.json` | 验证库结构、迁移、种子 |
