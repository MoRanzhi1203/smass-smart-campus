# 01 Seed 系统（组织与人员）

> 入口：`python manage.py seed_campus --settings=smass.settings_simulation`
> 隔离库：`smass_simulation`（前缀硬校验，禁止指向 `smass`）。

---

## 1. 命令

```powershell
# 干运行（只计算，不写库）
python manage.py seed_campus --profile medium --seed 20261101 --dry-run

# 只跑组织
python manage.py seed_campus --profile medium --stage org

# 组织 + 学生
python manage.py seed_campus --profile medium --stage org,students

# 调试规模
python manage.py seed_campus --profile small --colleges 1 --majors 2 `
  --grades 2 --classes-per 1 --students-per 5

# 限制学生总数
python manage.py seed_campus --profile medium --limit 500
```

参数：`--profile`（small/medium/large）、`--seed`、`--stage`、`--dry-run`、
`--limit`、`--batch-code`、规模覆盖（`--colleges` 等）。

## 2. 档位

| 档位 | 学院 | 专业 | 年级 | 班 | 学生 |
|---|---|---|---|---|---|
| small | 3 | 6 | 3 | 36 | 1080 |
| medium | 6 | 18 | 4 | 216 | 6480 |
| large | 10 | 35 | 4 | 560 | 16800 |

## 3. 幂等与批次

- 批次编码默认 `{profile}-{seed}-{stage}`，`SimulationBatch` 记录状态/阶段/统计/耗时；
- 组织按 `code`（`SIM-COL/MAJ/GRD/CLS-*`）`update_or_create`；
- 学生按 `login_name`（`sim_stu_<学号>`）判重，已存在则跳过；
- `SimulationObject` 记录 batch 与对象主键，供**按批次精确清理**（后续 `--cleanup`）；
- 重复执行同一 seed：`created = 0`，计数不变（已实测）。

## 4. 组织规则

```
学院(college) → 专业(major) → 行政班(class)
学院(college) → 年级(grade)   （年级不挂班级，保证 class.parent 恒为 major）
```

班级编码 `SIM-CLS-<专业4位>-<年份>-<序号>`，学号 `S<年份4位><序号5位>`（10 位，
与 `StudentProfile.student_no` 列宽一致）。

## 5. PII 与安全

- 姓名由姓氏库 + 名字库组合生成，非真实名单；
- 手机号使用 `100` 开头 11 位（无效号段），不生成身份证与邮箱；
- 账号密码由 `SIMULATION_PASSWORD` 提供（默认仅演示值），命令输出**不打印密码**。

## 6. 实测（2026-11-01）

| 场景 | 结果 |
|---|---|
| dry-run（1 学院/2 专业/2 年级/4 班/20 人） | 不写库，报告正确 |
| small 全量 | 3/6/9/36/1080 学生，**1.9 s** |
| 同一 seed 重跑 | `created: 0`（幂等） |
| medium 全量 | 6/18/24/216/6480 学生，**8.9 s** |
| 对象索引 | org 9 + record + account 均登记（`SimulationObject`） |
| 测试 | `smass_simulation` 3 例 + `smass_dormitory` 10 例，全绿 |

## 7. P3 岗位反推（staff 阶段）

公式（可在常量中调整）：

```
教学班 = 班数 × 8（每班每学期 8 门课）
总周学时 = 教学班 × 3
教师数 = ceil(总周学时 / 12)（教师最大周授课 12 学时）= 班数 × 2
辅导员数 = ceil(班数 / 8)
班主任 = 每班 1 名（从教师池选派，可带多班）
学院管理 = 每学院 3 人（管理员 / 教学经办 / 学生事务），统一最小权限 college_admin
```

生成内容：`Account`（`sim_tea_T######` / `sim_adm_XX_role`）+ `TeacherProfile` +
`AccountRole(teacher)` + `OrganizationMembership`（college 的 teacher、班级的
counselor / head_teacher）。

| 实测（medium） | 结果 |
|---|---|
| 教师 | 432（工号 T000001–T000432） |
| 辅导员 | 27 人，覆盖 216 班（每人 8 班） |
| 班主任 | 216 条（每班 1 人） |
| 学院管理 | 18（6 学院 × 3） |
| `system_admin` 授予 | **0**（最小权限） |
| 耗时 | 约 1.2 s |
| 幂等 | 重跑 `created=0`、关系数不变 |

> 幂等实现：教师/管理员按 `login_name` 判重；辅导员/班主任关系先删除
> `SIM-CLS-*` 班级上的同类关系再重建（MySQL 无部分唯一索引）。

---

## 8. P4 教学与排课（teaching 阶段）

| 项 | 生成规则 |
|---|---|
| 学年学期 | `SIM-2025`（2025-09-01 ~ 2026-08-31），学期 1 为当前 |
| 教室 | 3 栋教学楼 × 80 间 = 240 间，容量 60 |
| 课程 | 每专业 6 门（4 必修 + 2 选修）+ 2 门公共课（高数/大英） |
| 教学班 | 每行政班 8 门 → medium **1728** 个（`SEC-<班>-<序号>`） |
| 任课 | 本院教师池轮询，每教师 4 个教学班 |
| 修读群体 | 每班 1 个 `COH-<班>`，与班级一一对应 |
| 排课 | 每周 1 次、每次 **2 节连排**（1-2 / 3-4 / 5-6），教室不跨节换 |
| 验证 | 生成后调用 `solver.verify_run`，**hard_conflicts = 0** |
| 选课 | 每班学生选本班 8 个教学班 → medium **51840** 条 |

**约束校验**：教室/教师/修读群体三类硬冲突由贪心保证 + `verify_run` 独立复核；
教师每日 ≤5 节；教学班容量 = 班人数 + 10。

| 实测（medium） | 结果 |
|---|---|
| 教学班 / 排课条目 / 选课 | 1728 / 3456 / 51840 |
| 硬冲突 | **0** |
| 耗时 | 约 45 s |
| 幂等 | 重跑后计数不变（1728/3456/51840） |

排课容量依据：每班每周 8 次课 × 2 节 = 16 节 ≤ 30 个时段；240 间教室 × 3 个双节起点 × 5 天 = 3600 个双节槽 ≥ 1728 需求。

---

## 9. P5 宿舍仿真（dorms 阶段）

容量公式：

```
住宿学生 = 学生数 × 85%
房间数   = ceil(住宿学生 / 4 × 1.05)（预留 5% 空床）
楼栋数   = ceil(房间数 / 120)（每栋 6 层 × 20 间）
床位     = 楼栋数 × 120 × 4
```

| 实测（medium） | 结果 |
|---|---|
| 住宿学生 / 床位 | 5508 / 6240（13 栋、1560 间） |
| 分配 | 5508 条活跃住宿关系，床位占用 5508 |
| 宿管 | 15 个账号（13 楼管 + 1 主管 + 1 维修），15 条楼栋范围 |
| 调宿 / 退宿 | 34 / 16（覆盖 completed / submitted / rejected） |
| 报修 / 巡查 | 60 / 40（覆盖 5 种报修状态、正常与问题巡查） |
| 一致性 | 活跃分配 5508 = 占用床位 5508；重复学生 0、重复床位 0 |
| 耗时 / 幂等 | 约 28 s；重跑分配不变、宿管新增 0 |

分配顺序：学生按「班级 → 学号」排序后依次填充床位，天然实现同班优先
（同班学生相邻床位、多数同房）；每 4 人一间。

宿管权限：账号统一 `college_admin`（可登录管理端），实际可见范围由
`DormManagerScope` 按楼栋约束，**不授予 system_admin**。

---

## 10. P6 校园生活（campus 阶段）

以已生成的学生、教师、班级为输入，生成六类业务数据：

| 业务 | 规则 | medium 规模 |
|---|---|---|
| 考勤 | 每班 2 场（近一周），每场全班记录；出勤 85% / 迟到 10% / 缺勤 5% | 432 场 / **12960** 记录 |
| 请假 | 随机学生，类型病假/事假，状态轮换 已批准/待审/已驳回 | 300 |
| 社团 | 20 个社团（4 类轮换），每社团 25 名成员（1 名负责人），1 条会长任职 | 20 / 500 |
| 活动 | 40 场（讲座/社团/第二课堂/志愿），每场 20 人报名（含候补与签到），结束活动生成学分 | 40 / 800 |
| 财务 | 3 个收费项、每生 1 张账单（6800 元）、约 60% 缴费并刷新账单状态 | 6480 账单 / 3902 缴费 |
| 通知 | 400 条站内通知，`event_key` 幂等、`recipient_account` 指向真实账号 | 400 |

| 项 | 结果 |
|---|---|
| 耗时 | 约 9.6 s |
| 幂等 | 重跑后计数不变（432/12960/300/20/500/40/800/6480/3902/400） |
| 一致性 | 账单已缴 = 成功缴费合计；活动报名含候补/签到；学分仅对结束活动生成 |

---

## 11. P7 完整性校验（`--verify`）

```powershell
python manage.py seed_campus --verify `
  --report .local/evidence/v21/verify_medium.json `
  --settings=smass.settings_simulation
```

15 项跨模型检查：`student_triplet`（学籍/档案/账号一致）、`class_parent_is_major`、
`section_has_teacher`、`enrollment_within_capacity`、`schedule_no_conflicts`、
`class_exactly_one_head_teacher`、`counselor_within_8_classes`、
`dorm_active_unique`、`bed_occupied_matches_assignments`、`room_within_capacity`、
`activity_within_capacity`、`club_has_active_leader`、
`bill_paid_matches_payments`、`notification_recipient_exists`、
`leave_status_valid`。

| 实测（medium） | 结果 |
|---|---|
| 通过率 | **15 / 15 = 100%** |
| 分布 | 学院学生数、班级数、学籍状态、宿舍占用、账单状态、活动状态、考勤状态、教师/社团/通知数 |
| 宿舍 | 13 栋 / 1560 间 / 6240 床 / 5508 占用（88.3%） |
| 学籍状态 | 在读 6164 / 毕业 179 / 休学 137 |
| 财务 | 已缴 3902 / 未缴 2578（已缴 = 成功缴费合计） |

报告同时写入 JSON（失败样本最多 5 条），便于复核与回归。

---

## 12. 已知限制（后续阶段）

- 学生状态目前按年级分布（在读/休学/毕业），尚未接入选课、考勤、请假等业务状态；
- 教师/辅导员/班主任/学院管理员尚未生成（P3）；
- 清理命令 `--cleanup` 尚未实现（当前用隔离库脚本重置）；
- 年级节点按学院重复（每学院 4 个年级），用于展示层级；班级仍挂专业。
