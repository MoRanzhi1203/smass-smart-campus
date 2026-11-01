# 04 账号与身份合并

> 结论：**不做跨库账号复制式合并**。campus 库以确定性生成器重建校园身份（同 seed），
> 仅从产品库保留 1 个系统管理员账号，其余演示账号丢弃。

---

## 1. 决策表

| 来源 | 数据 | 决策 | 理由 |
|---|---|---|---|
| product | `dev_admin`（system_admin） | **PRESERVE** | 唯一系统管理员，campus 生成器按最小权限不产生 system_admin |
| product | `dev_student` / `dev_teacher` | **DISCARD** | 演示样本（7 学籍 / 5 教师），与 large 校园数据重复 |
| product | 7 学籍 / 5 教师档案 / 19 组织单元 | **DISCARD** | 旧演示样本，重新生成为正式校园数据 |
| simulation | 17984 账号 / 16800 学籍 / 1120 教师 | **REGENERATE** | 同一 seed（20261101）在 campus 重新生成，避免 PK/学号/登录名冲突 |
| unified_verify | 3 账号 / 1 学籍 / 1 教师 | **DISCARD** | 结构落后（缺宿舍/通知外键），仅验证证据，无业务价值 |

## 2. 实际执行

- `dev_admin` 从 `smass_product_dev.r21_account_account` 读取（含密码哈希），
  写入 campus 并授予 `system_admin`；**密码哈希原样复制**，不落明文。
- 复制后校验：`dev_admin` 存在，`active_roles() == ['system_admin']`。
- 其余账号不复制；campus 账号由生成器创建：
  - 学生 16800（`sim_stu_S{年份}{序号}`）
  - 教师 1120（`sim_tea_T######`）
  - 学院管理 30（`sim_adm_{学院}_{角色}`，仅 `college_admin`）
  - 宿管 34（`sim_dorm_m01..m32` + 主管 + 维修）

## 3. 角色不升级保证

| 角色 | campus 是否授予 | 说明 |
|---|---|---|
| `system_admin` | 仅 `dev_admin` 1 个 | 最小化超级管理员数量 |
| `college_admin` | 30 个学院管理 + 34 宿管 | 范围由 `DormManagerScope` / 学院归属约束 |
| `teacher` / `student` | 1120 / 16800 | 与学生/教师档案一一对应 |

生成器 `staff.py` 明确不授予 system_admin（V2.1 起），本次未放宽。

## 4. 冲突处理方式

不做逐行导入，因此不存在：主键冲突、学号/工号/登录名冲突、角色关系冲突。
campus 内部数据由同一生成器在同一事务性批次中产生，天然自洽；
`--verify` 的 `student_triplet`（学籍/档案/账号一致）实测通过。
