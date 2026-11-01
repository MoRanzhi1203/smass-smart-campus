# SMASS V2.1 · 全校仿真数据集与宿舍管理模块 · 架构与计划

> 基线：`ef89ab3`（V2.0 交付），配置 `smass.settings_product`，库 `smass_product_dev`。
> 约束：不重建旧库 `smass`；不接真实支付；不使用真实 PII；不覆盖产品库未知数据；
> 仿真数据先在**隔离库**开发验证，再提供受控导入。

---

## 1. 现状基线（核验结论）

| 项 | 现状 |
|---|---|
| Git HEAD | `ef89ab3`，工作区干净 |
| 产品库 | `smass_product_dev`（131 表，含 V2.0 全部业务） |
| 住宿现状 | 仅 `StudentRecord.extra['dormitory']`（只读展示）；`smass_facilities` 有 `Building`/`Room`，**无**寝室/床位/分配/调宿/报修/巡查模型 |
| 宿舍 app | **不存在**（`smass_dormitory` 需新建） |
| 仿真 seed | 仅 `scripts/product_bootstrap.py`（固定演示数据）；**无**版本化大规模生成系统 |
| 岗位 | `AccountRole`（角色）+ `OrganizationMembership`（组织成员）；无宿管岗位 |
| 排课 | `smass_scheduling` 求解器 + `ScheduleRun/Entry` + `ScheduleException`（V2.0） |

设计取舍：**复用 `smass_facilities.Building/Room` 作为楼栋/房间唯一权威**，宿舍模块以一对一扩展表补充宿舍语义，不新建第二套楼宇表。

---

## 2. 目标架构

```
scripts/simulation/
├── __init__.py
├── config.py          # 档位（small/medium/large）与自定义规模
├── rng.py             # 全局确定性随机（seed 派生）
├── batch.py           # SimulationBatch 记录、阶段状态、断点恢复
├── org.py             # 学校/校区/学院/专业/年级/行政班
├── people.py          # 学生账号、教师、辅导员、班主任、管理人员
├── teaching.py        # 课程/教学班/任课/排课/选课
├── dorms.py           # 宿舍资源、分配、调宿、退宿、报修、巡查
├── campus_life.py     # 社团/活动/志愿/学生组织/考勤/请假/财务/通知
├── verify.py          # 跨模型一致性校验与分布报告
└── cleanup.py         # 按 batch 清理
```

统一入口（Django 管理命令）：

```powershell
python manage.py seed_campus --profile medium --seed 20261101 `
  --settings=smass.settings_simulation --stage all --dry-run
python manage.py seed_campus --profile medium --seed 20261101 --stage org,people
python manage.py seed_campus --verify --batch <id>
python manage.py seed_campus --cleanup --batch <id> --confirm
```

阶段：`org → people → staff → teaching → dorms → campus_life → verify`。

---

## 3. 规模档位

| 档位 | 学院 | 专业 | 年级 | 每专业每年级班 | 每班学生 | 行政班 | 学生 |
|---|---|---|---|---|---|---|---|
| small | 3 | 6 | 3 | 2 | 30 | 36 | 1080 |
| medium | 6 | 18 | 4 | 3 | 30 | 216 | 6480 |
| large | 10 | 35 | 4 | 4 | 30 | 560 | 16800 |

教师/辅导员/班主任/管理员数量**由工作量与配置反推**，不预设固定值：

- 任课教师：`Σ(教学班周学时) / 教师最大周授课量`，并按专业方向分配可授课程；
- 辅导员：`行政班数 / 每辅导员负责班数上限（默认 8）`；
- 班主任：每行政班 1 人（优先本院教师，采用岗位关系而非新角色）；
- 学院管理员：每学院 1 名 `college_admin` + 教学/学工经办各 1（最小权限）。

---

## 4. 批次、幂等与清理

新增 `smass_simulation` app：

| 模型 | 字段 |
|---|---|
| `SimulationBatch` | `code`(唯一，如 `med-20261101-a1`)、`profile`、`seed`、`status`、`stage_done`(JSON)、`counts`(JSON)、`created_at`、`note` |
| `SimulationObject` | `batch` FK、`model_label`、`object_pk`、`created_at`（用于精确清理） |

幂等策略：

- 业务对象均写入稳定业务键（学号/工号/班级编码/课程编码/楼栋编码/房间编码/床位号）；
- `get_or_create` 或 `update_or_create`，重复执行不产生重复；
- 账号登录名统一前缀 `sim_`，便于识别与批量清理；
- `--dry-run` 只统计不写库；`--stage` 支持断点续跑；
- 清理**只删** `SimulationObject` 指向的对象（按 batch），不做全库清空。

---

## 5. 宿舍领域模型（`smass_dormitory`）

复用 `smass_facilities.Building/Room`（唯一楼栋/房间权威），新增：

| 模型 | 说明 | 关键约束 |
|---|---|---|
| `DormZone` | 宿舍区（校区内） | `code` 唯一 |
| `DormBuilding` | 楼栋宿舍属性（1:1 Building） | `building` 唯一；性别策略、楼长、状态 |
| `DormRoom` | 寝室（1:1 Room） | `room` 唯一；容量 4/6；状态（可用/停用/维护） |
| `Bed` | 床位 | `(room, number)` 唯一；状态（空闲/占用/停用） |
| `DormAssignment` | 住宿关系 | `student` + `active_slot` 唯一（活跃唯一，MySQL 无部分索引）；`bed` + `active_slot` 唯一 |
| `DormChangeRequest` | 调宿申请 | from_bed/to_bed、状态机、审批人 |
| `DormCheckoutRequest` | 退宿申请 | 状态机、退宿时间 |
| `DormRepair` | 报修工单 | 房间/床位、状态机、分派人 |
| `DormInspection` | 巡查记录 | 楼栋/房间、检查项、结论、整改状态 |
| `DormManagerScope` | 宿管岗位范围 | `account` + `building` 唯一；岗位类型（主管/楼管/维修） |

MySQL 兼容技巧：`active_slot`（活跃=1，历史=NULL）+ 普通唯一约束，实现“同一学生/床位同时只有一条活跃关系”（`NULL` 不参与唯一冲突）。

业务规则：

- 分配/调宿在 `transaction.atomic()` + `select_for_update()` 内校验床位空闲与房间容量；
- 房间停用/楼栋维护时禁止分配与调宿；
- 报修/巡查状态机只能前进，非授权人员（非该楼栋宿管、非管理员）返回 403；
- 每名学生同一时刻最多一条 `active` 住宿关系；每个床位同一时刻最多一名在住学生。

岗位授权（不新建登录表）：

- 复用 `AccountRole`：`college_admin`（宿舍主管）/ 新增 `dorm_manager`（楼管）/ `dorm_repair`（维修）——是否新增角色码在实现时评估；
- `DormManagerScope` 绑定账号与楼栋，视图层按楼栋过滤；
- 宿管默认**无**学籍/课程/财务写权限。

---

## 6. UI 与入口

| 入口 | 说明 |
|---|---|
| `/student/dormitory/` | 重构：楼栋/楼层/寝室/床位/室友/状态（未分配/走读/待审核）+ 报修/调宿/退宿 + 申请历史 |
| `/dormitory/`（新工作台） | 宿管专用：楼栋数/入住/床位/空余/今日入退/待审批调宿/待处理报修/异常巡查 |
| `/admin/dormitory/`（管理端） | 宿舍资源、分配、调宿审批、报修、巡查、统计、导入导出 |

全部沿用 V2.0 `app.css` 令牌与三端壳，不引入新框架。

---

## 7. 分阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 本设计文档、`settings_simulation`、隔离库、`smass_simulation` + `smass_dormitory` 骨架与迁移 | 迁移可回滚；库可重建 |
| P1 | 组织生成（学校/校区/学院/专业/年级/班级）+ 报告 | 组织树、学院/专业/班级人数一致 |
| P2 | 学生账号 + Profile + Record + 分布状态 | 学号唯一、班归属合法、无真实 PII |
| P3 | 教师/辅导员/班主任/学院管理员（反推） | 岗位需求报告、最小权限、范围校验 |
| P4 | 课程/教学班/任课/排课（求解器）/选课 | 无硬冲突、容量合规、验证器通过 |
| P5 | 宿舍资源与分配/调宿/退宿/报修/巡查 | 活跃唯一、容量与状态约束、越权 403 |
| P6 | 社团/活动/志愿/组织/考勤/请假/财务/通知 | 跨模型一致（负责人是成员、报名不超容量等） |
| P7 | 完整性校验 + 分布统计 + 失败样本 | `--verify` 报告通过率 |
| P8 | 性能与浏览器验收（small/medium/large） | p50/p95/p99、查询数、分页 |
| P9 | 文档与账本收尾 | 11 份 V2 文档 + 本目录文档更新 |

---

## 8. 安全与合规

- 手机号使用 `1990000xxxx` 段（明确无效）；邮箱 `.test`；身份证不生成或用测试占位；
- 姓名使用合成姓名库，不与真实个人对应；
- 密码由 `.env` 的 `SIMULATION_PASSWORD` 提供，命令输出**不打印密码**；
- 隔离库 `smass_simulation`（前缀硬校验），绝不允许指向 `smass` 或生产库；
- 清理必须显式 `--confirm` 且限定 batch。
