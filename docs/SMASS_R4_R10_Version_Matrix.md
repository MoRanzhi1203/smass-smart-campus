# SMASS R4–R10 完成矩阵与发行候选

- 分支：`feat/smass-r4-r10-integrated-platform`
- 基线：`01fe357`
- **36/36 强制任务 TESTED**
- 门禁：`scripts/r4_r10_gate.py --strict` → **exit 0**
- **R10 = RELEASE_CANDIDATE**（`PRODUCTION_DEPLOYMENT = NOT AUTHORIZED`）

## 1. 逐版本状态

| 版本 | 状态 | 模型 | 页面/端点 | 测试 | 关键能力 |
|---|---|---|---|---|---|
| **R4** | **TESTED** | 7 | 9 路由 + 2 页 | **69** | 组织树防环、组织 scope、乐观锁、受限导出、浏览器 E2E |
| **R5** | **TESTED** | 7 | 15 路由 + 6 页 | **56** | 学年/学期/课程/教学班/任课/修读、三端可见性 |
| **R6** | **TESTED** | 7 | 8 路由 + 4 页 | **41** | 版本化流程、状态机、待办、通知、UI walkthrough |
| **R7** | **TESTED** | 5 | 4 路由 + 2 页 | **31** | 指标注册、scope 先于聚合、小样本抑制、报表导出 |
| **R8** | **TESTED** | 4 | 6 端点 | **23** | /api/v1/、服务身份、限流、幂等、mock 同步、OpenAPI |
| **R9** | **TESTED** | 4 | 4 端点 | **21** | 遥测、health/ready、告警、CI、备份演练、秘密扫描 |
| **R10** | **RELEASE_CANDIDATE** | — | 1 路由 + 2 页 | **10** | 统一导航、安装、升级回滚、运维手册、全链路 E2E |

## 2. 36 项强制任务

| 版本 | 任务 | 状态 |
|---|---|---|
| R4 | R4-01 组织 scope（P0） | TESTED |
| R4 | R4-02 并发安全（P0） | TESTED |
| R4 | R4-03 受限导出 | TESTED |
| R4 | R4-04 浏览器 E2E | TESTED |
| R4 | R4-05 集成验收 | TESTED |
| R5 | R5-01..05 | TESTED |
| R5 | R5-06 端到端 | TESTED |
| R6 | R6-01..04 | TESTED |
| R6 | R6-05 演示流程 | TESTED |
| R7 | R7-01..05 | TESTED |
| R8 | R8-01..05 | TESTED |
| R9 | R9-01..05 | TESTED |
| R10 | R10-01..05 | TESTED |

## 3. 全量回归

| 套件 | 用例 |
|---|---|
| `smass_operations`（R9+R10） | **31** |
| `smass_api`（R8） | 23 |
| `smass_analytics`（R7） | 31 |
| `smass_workflow`（R6） | 41 |
| `smass_academic`（R5） | 56 |
| `smass_organization`（R4） | 69 |
| `r22_account` | 94 |
| `r21_account` | 72 |
| `app01` | 114 |
| `tests_e2e` | 16 |
| **合计** | **547** |

`check` 0 issues；`makemigrations --check` No changes；`smass` 26 表 / Admin 1 · Student 3 · Teacher 2 未变。

## 4. R10 发行门禁

| 门禁 | 结果 |
|---|---|
| 全链路 E2E（R4→R5→R6→R7→R8） | **PASS** |
| 跨模块 scope 一致性 | **PASS**（服务层/指标/API 三处一致） |
| 全新库从零安装 | **PASS**（72 表、0 缺失） |
| 模块级迁移回滚 | **PASS**（72→66→72，其他数据存活） |
| 导航可达 | **PASS**（6 个入口全部 200/鉴权后可用） |
| 移动端视口 | **PASS**（导航堆叠） |
| 秘密扫描 | **PASS**（0 issues / 33 fixtures） |
| 依赖审计 | **PASS**（0 漏洞） |

## 5. 未解决事项

| 项 | 状态 | 说明 |
|---|---|---|
| BD-05/06/07/08 | **BUSINESS_CONFIG_PENDING** | 成绩规则、审批链、指标口径、外部协议——需业务方输入；**未阻断任何已实现能力** |
| MySQL 条件唯一约束 | 已知限制 | 两个约束未在 DB 创建，靠服务层保证 |
| 生产部署 | **NOT AUTHORIZED** | 需单独授权 |
| `smass_r22_g5_stage` | 未清理 | 含真实姓名，需数据责任人批准 |

## 6. 结论

**R10 = RELEASE_CANDIDATE**：36/36 强制任务 TESTED，547 测试全绿，全链路 E2E 与安装/升级/回滚演练均通过。

**`PRODUCTION_DEPLOYMENT = NOT AUTHORIZED`** —— 候选状态不等于上线许可。
