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

## 7. 已知限制（后续阶段）

- 学生状态目前按年级分布（在读/休学/毕业），尚未接入选课、考勤、请假等业务状态；
- 教师/辅导员/班主任/学院管理员尚未生成（P3）；
- 清理命令 `--cleanup` 尚未实现（当前用隔离库脚本重置）；
- 年级节点按学院重复（每学院 4 个年级），用于展示层级；班级仍挂专业。
