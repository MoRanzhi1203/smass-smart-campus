# 01 现有数据库清单（实测）

> 采集时间：V2.2 启动时；采集方式：Django shell + `SHOW DATABASES` + `information_schema`。
> 基线 Git：`eb456e2`；工作区干净。

---

## 1. 实际 MySQL 实例中的 SMASS 相关库

`SHOW DATABASES` 结果中与 SMASS 相关、且**本次任务涉及**的三个：

| 数据库 | 用途 | 表数 | 账号 | 学籍 | 学生档案 | 教师档案 | 组织单元 | 迁移数 |
|---|---|---|---|---|---|---|---|---|
| `smass_product_dev` | V2.0/V2.1 产品开发库 | **141** | 15 | 7 | 7 | 5 | 19 | 54 |
| `smass_simulation` | V2.1 仿真库（large） | **143** | 17984 | 16800 | 16800 | 1120 | 645 | 56 |
| `smass_unified_verify` | 统一迁移验证库 | **127** | 3 | 1 | 1 | 1 | 4 | 47 |

- `smass_campus`：**不存在**（可安全创建）。
- 原始库 `smass`：**不存在**（早已物理删除，严禁重建）。

## 2. 实例中的其他库（不在本任务范围，不得触碰）

实例中还存在大量其他项目与历史演练库，例如 `agri_db`、`school`、`ruoyi`、`smass_pmr_*`、
`smass_r4_*`、`smass_r22_*`、`smass_integrated_dev`、`smass_demo`、`smass_h5_*` 等。
**本任务不删除、不修改这些库**；仅处理上表三个。

## 3. 结构与迁移差异

| 项 | product | simulation | unified_verify |
|---|---|---|---|
| 最新 V2 迁移 | dormitory/0001、workflow/0004、finance/0002 | 含 simulation/0002 | 停留在 workflow/0003，**缺** V2.0/V2.1 新模型 |
| 宿舍模块 | 已建（9 表） | 已建 | **未建** |
| 通知外键 | 已建 | 已建 | 未建 |
| 退费双人审批 | 已建 | 已建 | 未建 |

结论：`unified_verify` 结构落后，**不作为最终数据来源**；`product` 与 `simulation` 结构接近最新。

## 4. 当前运行环境

| 项 | 实测 |
|---|---|
| 8050 端口服务 | 仿真配置 `--settings=smass.settings_simulation`（切换前的产品服务已停止） |
| 数据库目标 | `smass_simulation` |
| 登录页 | 200 |
| 三端/宿管走查 | 28/28 PASS（`.local/evidence/v21/walkthrough_8050.json`） |

## 5. 代码引用扫描

- **业务代码**（`smass_workspace`、`smass_*` 业务 app）**不硬编码库名**，只依赖 Django 配置；
- 库名硬编码集中在：`smass/settings_*.py`（均为前缀硬校验配置）、`scripts/db_unify*.py`、
  `scripts/legacy_*.py`、`scripts/product_*.py`（历史迁移/演练工具，仅操作隔离库）；
- 测试使用 `TEST.NAME`（`test_smass_*`），由测试框架自动创建/销毁，不连业务库。

## 6. 数据内容初判（供 03 决策）

| 数据类别 | product | simulation | 决策初判 |
|---|---|---|---|
| 校园人员（16800 学生 / 1120 教师 / 30 学院管理 / 34 宿管） | 无 | 有（large） | **REGENERATE**（同 seed 在 campus 重建） |
| 系统身份与权限（system_admin 账号、角色组） | `dev_admin` 等 | **无 system_admin** | **PRESERVE** `dev_admin` 及必要配置 |
| 学籍/课程/排课/宿舍/活动/社团/财务/通知 | 7 学生演示样本 | large 全量 | 演示样本 **DISCARD**；large 重新生成 |
| 系统配置（字段定义等） | 有 | 部分 | 逐表 **PRESERVE/REVIEW** |
| unified_verify 迁移证据 | — | — | **DISCARD**（仅留档） |

## 7. 待确认项（REVIEW，不自动处理）

- `product` 中 `StudentFieldDefinition` 等配置是否为演示专用；
- `product` 中 `dev_admin` 是否保留为校园库唯一系统管理员；
- `unified_verify` 是否存在不可再生成的验证证据（目前仅 3 账号 / 1 学籍，判断为可丢弃）。
