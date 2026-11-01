# 03 数据来源优先级与决策

---

## 1. 优先级

1. **数据结构**：Git 最新 Django 模型与迁移（campus 从零迁移）；
2. **校园人员与组织**：V2.1 large 基线（10 学院 / 35 专业 / 4 年级 / 560 班 / 16800 学生 / 1120 教师 / 30 学院管理 / 34 宿管）；
3. **系统身份与配置**：从 `smass_product_dev` 保留必要项；
4. **unified_verify**：不作为数据来源。

## 2. 逐类决策

| 数据类别 | 来源 | 决策 | 执行方式 |
|---|---|---|---|
| 表结构 | Git 迁移 | REGENERATE | `migrate` 从零 |
| 学院/专业/年级/班 | large 基线 | REGENERATE | 生成器（同 seed 20261101） |
| 16800 学生 + 账号/档案 | large 基线 | REGENERATE | 生成器 |
| 1120 教师 + 导师/班主任/辅导员关系 | large 基线 | REGENERATE | 生成器（按工作量反推） |
| 30 学院管理账号 | large 基线 | REGENERATE | 生成器（仅 college_admin） |
| 34 宿管账号 + 楼栋范围 | large 基线 | REGENERATE | 生成器 |
| 课程/教学班/排课/选课 | large 基线 | REGENERATE | 生成器 + `verify_run`（0 冲突） |
| 宿舍资源/住宿/调宿/退宿/报修/巡查 | large 基线 | REGENERATE | 生成器（32 栋/15360 床/14280 在住） |
| 考勤/请假/社团/活动/志愿/财务/通知 | large 基线 | REGENERATE | 生成器 |
| `dev_admin`（system_admin） | product | **PRESERVE** | 复制账号（密码哈希原样）+ 授角色 |
| `dev_student` / `dev_teacher` | product | DISCARD | 演示样本 |
| product 7 学籍 / 5 教师 / 19 组织单元 | product | DISCARD | 与 large 重复 |
| 学生字段定义（StudentFieldDefinition） | product | REVIEW | 实测该表 0 行，无数据可迁移 |
| unified_verify 3 账号 / 1 学籍 | unified_verify | DISCARD | 结构落后，仅验证证据 |

## 3. 为何用“重建”而非“复制 16800 行”

| 复制导入 | 确定性重建（采用） |
|---|---|
| 需处理 PK/学号/登录名/组织编码/课程编码冲突 | 无冲突（campus 内新生成） |
| 需维护源→目标 ID 映射与事务边界 | 单批次事务，天然自洽 |
| 失败易留半成品 | 可重复执行、幂等 |
| 需要 130+ 表的外键顺序 | 生成器按依赖顺序写入 |

代价：数据为“同 seed 的等价重建”，不是逐字节复制；已用 `--verify` 与规模核对证明等价（16800/1120/560/4480/134400/32/15360/14280）。

## 4. 时间与批次记录

| 阶段 | 耗时 |
|---|---|
| org + students + staff | 19.4 s |
| teaching + dorms + campus | 205.4 s |
| 内容美化 + 保留 | 数秒（幂等） |
| 完整性校验 | 15/15 |
