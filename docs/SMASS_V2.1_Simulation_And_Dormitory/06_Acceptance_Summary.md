# 06 V2.1 验收汇总

> 范围：①版本化仿真数据系统 ②组织与学生规模 ③岗位反推 ④教学/排课/选课 ⑤宿舍业务域与三端 UI
> ⑥完整性校验/分布/性能/浏览器验收 ⑦沿用 V2.0 设计系统。
> 约束：未重建旧库 `smass`；未接真实支付；未使用真实 PII；未 force push。

---

## 1. 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 隔离配置、`smass_simulation`、`smass_dormitory` 骨架与迁移 | 完成 |
| P1/P2 | 组织（学院/专业/年级/班级）与学生账号/学籍 | 完成 |
| P3 | 教师/辅导员/班主任/学院管理反推与最小权限 | 完成 |
| P4 | 课程/教学班/任课/排课（verify_run）/选课 | 完成 |
| P5 | 宿舍资源反推、分配、调宿、退宿、报修、巡查、宿管 | 完成 |
| P5-UI | 学生住宿页、宿管工作台、管理端宿舍 | 完成 |
| P6 | 考勤/请假/社团/活动/志愿/财务/通知 | 完成 |
| P7 | 完整性校验与分布报告（`--verify`） | 完成 |
| P8 | 页面性能采样与 N+1 修复 | 完成 |
| P9 | 安全清理（`--cleanup`）、断点续跑（`--resume`）、重建验证 | 完成 |
| large | 16800 规模生成/校验/性能 | 完成 |

## 2. 规模与耗时

| 档位 | 学生 | 教学班 | 选课 | 住宿分配 | 总耗时 |
|---|---|---|---|---|---|
| small | 1080 | 288 | 8640 | 918 | 约 15 s（各阶段合计，未单独计时） |
| medium | 6480 | 1728 | 51840 | 5508 | 约 71 s（清理后重建） |
| large | 16800 | 4480 | 134400 | 14280 | 约 193 s |

## 3. 校验与性能

| 项 | 结果 |
|---|---|
| `--verify`（medium） | 15 / 15 = 100% |
| `--verify`（large） | 15 / 15 = 100% |
| 页面性能（medium/large） | 12 页，26–45 SQL，28–90 ms；分页生效 |
| N+1 修复 | 教学班名单 149 → 29 查询、127 → 59 ms |
| 产品主线回归（V2.0） | **150 例全绿**（新增宿舍 app 与迁移后仍通过） |
| V2.1 测试 | **26 例全绿**（生成 6 + 教学 3 + 宿舍 13 + 校园 2 + 校验 2） |
| 浏览器走查（medium） | 4 角色 × 12 页 × 2 视口 = **28 项，0 失败** |

## 4. 关键命令

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

# 生成（档位/种子/阶段/干跑/限制）
& $py manage.py seed_campus --profile medium --seed 20261101 `
  --stage org,students,staff,teaching,dorms,campus --settings=smass.settings_simulation

# 断点续跑（跳过已完成阶段）
& $py manage.py seed_campus --profile large --seed 20261101 --stage org,students,staff `
  --resume --settings=smass.settings_simulation

# 校验与报告
& $py manage.py seed_campus --verify --report .local/evidence/v21/verify_medium.json `
  --settings=smass.settings_simulation

# 清理
& $py manage.py seed_campus --cleanup --settings=smass.settings_simulation          # 计划
& $py manage.py seed_campus --cleanup --confirm --settings=smass.settings_simulation  # 执行

# 性能采样
& $py scripts\perf_simulation.py

# 浏览器走查
& $py manage.py runserver 127.0.0.1:8051 --settings=smass.settings_simulation --noreload
& $py scripts\walkthrough_simulation.py --base http://127.0.0.1:8051
```

## 5. 证据索引

| 证据 | 位置 |
|---|---|
| 设计/系统文档 | `docs/SMASS_V2.1_Simulation_And_Dormitory/00–06` |
| 生成器与命令 | `smass_simulation/generator/*`、`management/commands/seed_campus.py` |
| 宿舍域与 UI | `smass_dormitory/*`、`smass_workspace/services|views|templates/dormitory*` |
| 校验报告 | `.local/evidence/v21/verify_medium.json`、`verify_large.json` |
| 性能报告 | `.local/evidence/v21/perf_sim.json`、`perf_large.json` |
| 浏览器走查 | `.local/evidence/v21/walkthrough/*.png`、`walkthrough.json` |
| 测试 | `smass_simulation/tests/*`、`smass_dormitory/tests/*`、`smass_workspace/tests/test_workspace.py` |

## 6. 已知限制

- 单请求采样不是并发压测，未做 p95/p99；
- 宿舍资源的新建/编辑、按班级批量分床、住宿导入导出未做产品表单；
- 宿管工作台房间名册仅到房间级（未做床位级点名）；
- `StudentProfile` / `StudentRecord` 双份字段仍是“同步 + 检测”，未合并；
- large 未做浏览器走查；
- 仿真密码来自 `SIMULATION_PASSWORD`（默认演示值），生产需另行注入。
