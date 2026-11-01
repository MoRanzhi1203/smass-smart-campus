# 02 目标数据库架构（smass_campus）

> 结构权威 = Git 中最新 Django 模型与迁移，**不是**任何旧库的实际表结构。

---

## 1. 建库方式

```sql
CREATE DATABASE smass_campus CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
python manage.py migrate --settings=smass.settings_campus
```

- 迁移前确认库不存在（实测不存在 → 创建）；
- **从零执行 56 条迁移**，未复制旧表、未跳过迁移；
- 结果：143 张表。

## 2. 结构组成

| 层 | 内容 |
|---|---|
| 统一账号 | `r21_account`（Account/AccountRole/StudentProfile/TeacherProfile/审计/登录尝试） |
| 组织 | `smass_organization`（院/专业/年级/班、成员关系、学籍、学籍异动） |
| 教务 | `smass_academic`（学年学期/课程/教学班/选课/成绩） |
| 排课 | `smass_scheduling`（Cohort/Requirement/Entry/Run/Conflict/Constraint） |
| 考勤请假 | `smass_attendance`（场次/记录/请假/补签） |
| 宿舍 | `smass_dormitory`（区/楼/寝室/床位/住宿/调宿/退宿/报修/巡查/宿管范围） |
| 校园生活 | `smass_clubs`、`smass_activities`、`smass_forum`（社团/活动/通知公告） |
| 财务 | `smass_finance`（收费项/账单/明细/缴费/退费） |
| 工作流 | `smass_workflow`（任务/流程/通知，含 `recipient_account` 外键） |
| 场地 | `smass_facilities`（楼宇/房间/预约） |
| 运维与安全 | 监控/审计/API/数据交换/MFA |
| 生成器 | `smass_simulation`（批次日志与对象索引，仅审计用途） |

## 3. 与旧库的结构差异（为何不能直接沿用）

| 项 | unified_verify | product/simulation | campus（最新） |
|---|---|---|---|
| 宿舍 9 表 | 缺 | 有 | 有 |
| 通知收件人外键 | 缺 | 有 | 有 |
| 退费双人审批 | 缺 | 有 | 有 |
| 生成器批次表 | 缺 | 有 | 有 |

## 4. 测试隔离

```python
DATABASES['default']['TEST']['NAME'] = 'test_smass_campus'
```

- 测试库由 Django 自动创建/销毁；
- 业务库 `smass_campus` 不被测试写入（已用 28 + 156 例验证，运行后业务库数据量不变）。

## 5. 从零部署能力

新机器上只需：建库 → `migrate` → `seed_campus`（如需演示数据）→ `runserver`。
所有约束（唯一键、外键、索引、默认值）均由迁移建立，不依赖手工 SQL。
