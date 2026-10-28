# SMASS R4–R10 版本成果矩阵

> 状态词：`NOT_STARTED / IN_PROGRESS / CORE_COMPLETE / TESTED / PARTIAL / BLOCKED / BUSINESS_CONFIG_PENDING / RELEASE_CANDIDATE / RELEASED`
> 原则：只有真实实现且测试过的能力才记录；其余一律如实标注。

## 1. 总览

| 版本 | 主题 | 状态 | 真实交付 |
|---|---|---|---|
| **R4** | 组织机构与学生档案 | **CORE_COMPLETE / PARTIAL** | 7 模型、组织树服务、字段级权限、导入预检/提交、8 端点、2 模板、23 测试 |
| R5 | 教学管理与教师工作台 | **NOT_STARTED** | — |
| R6 | 审批工作流与消息 | **NOT_STARTED** | — |
| R7 | 数据分析与报表 | **NOT_STARTED** | — |
| R8 | 开放 API 与集成 | **NOT_STARTED** | — |
| R9 | 高可靠与安全运维 | **PARTIAL**（沿用 R2/R3） | 告警、审计、备份演练、连接诊断、三引擎浏览器 |
| R10 | 产品化与发行 | **NOT_STARTED** | — |

## 2. R4 明细

| 维度 | 内容 |
|---|---|
| 模型 | `OrganizationUnit`、`OrganizationMembership`、`StudentRecord`、`StudentRecordChange`、`StudentFieldDefinition`、`DataImportJob`、`DataImportRowError` |
| 迁移 | `smass_organization/migrations/0001_initial.py` |
| 服务 | 类型约束、防环（环优先）、移动审计、字段级权限、导入预检/提交 |
| 页面 | `/r4/units/`（组织列表，真实渲染）、`/r4/students/`（学生列表，字段级过滤） |
| API | `/r4/units/tree/`、`/r4/students/<no>/`、`/r4/import/preview|commit/`、`/r4/health/` |
| 测试 | 23 例 PASS |
| 缺失 | 组织级 scope、浏览器 E2E、并发更新测试、导出 |

## 3. R5–R10 为什么没开始

| 版本 | 缺什么 |
|---|---|
| R5 | 课程/学期/教学班的真实业务规则（是否要成绩、评分复核规则） |
| R6 | 审批场景清单（对象、审批链、驳回/撤回/超时规则） |
| R7 | 指标字典（每个指标的来源、口径、权限） |
| R8 | 外部系统清单与协议 |
| R10 | 依赖前六项稳定 |

按计划 §4 的 A/B/C 分级：R5–R8 的**模型骨架**属 A/B 类可做，但其**业务规则**属 C 类
（真实制度），已在业务决策登记册登记。

## 4. 结论

- R4 有可运行的真实能力（非空壳），但未达完整验收 → `CORE_COMPLETE / PARTIAL`；
- R5–R10 保持 `NOT_STARTED`，**没有创建任何空壳模型或演示页面**；
- 下一步建议：先补 R4 的组织级 scope + E2E，再启动 R5 骨架。
