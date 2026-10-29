# SMASS R10 表单与业务流程

> 逐模块记录：路由 → 视图 → 校验 → 服务 → 持久化 → 权限 → 审计 → E2E。
> 已被真实浏览器/测试验证的项标 ✅，未做标 ⬜。

## R4 组织与档案（U3）✅

| 操作 | 路由 | 方法 | 角色 | 服务 | 持久化 | 错误处理 | 证据 |
|---|---|---|---|---|---|---|---|
| 组织新建表单 | `/r4/units/new/` | GET | system_admin | — | — | — | `u3_01_unit_new.png` |
| 组织新建提交 | `/r4/units/new/` | POST | system_admin | `create_unit` | `OrganizationUnit` | 空编码/空名称/非法层级/重复编码 → 行内 + 顶部错误 | `test_create_unit_persists` 等 5 例 |
| 组织编辑 | `/r4/units/<pk>/edit/` | GET/POST | system_admin | `move_unit` | `OrganizationUnit` | 成环 → `id="form-error"` | `test_move_unit_cycle_rejected` |
| 学生列表 | `/r4/students/` | GET | admin/college/teacher | `scoped_students` | — | scope 为空 → 空态 | `test_r4_scope` |
| 学生详情 | `/r4/students/<no>/` | GET | 含 student | `can_access_student` | — | 越权/不存在 → **404**（不泄露存在性） | `test_detail_denied_for_other_college` |
| 学生编辑 | `/r4/students/<no>/edit/` | GET/POST | system/college admin | `update_student` | `StudentRecord` + `version` | **版本冲突 → 409** + "已被他人修改" | `test_version_conflict_returns_409` |
| 导入预览 | `/r4/import/preview/` | POST | admin | `import_preview` | **不写**（仅 `DataImportJob` 预览记录） | 行级错误逐条返回 | `test_preview_does_not_write` |
| 导入提交 | `/r4/import/commit/` | POST | admin | `import_commit` | `StudentRecord` upsert | 单行失败不阻断其他行 | `test_commit_persists_students` |
| 受限导出 | `/r4/students/export/` | GET | admin/college/teacher | `export_students_csv` | — | 公式注入中和 | `test_r4_export`（10 例） |

### 字段级权限的重要修正

`services.editable_fields(account)` 返回的是 **`StudentFieldDefinition` 对象**
（扩展字段定义），**不是**基础字段名。因此：

```python
# 错误（永远为 False）
if 'name' in services.editable_fields(account): ...

# 正确：基础字段按角色判定
BASE_EDIT_ROLES = {'system_admin', 'college_admin'}
```

已在 `smass_organization/ui_views.py::_base_editable` 实现，并在文档中记录该陷阱。

### 关键安全语义（均有测试）

1. 越权访问他人学生 → **404**（不是 403，避免探测存在性）
2. 学生只能看自己（`record.account == 当前账号`）
3. 版本冲突 → **409**，且**服务端保留他人修改**（后写不覆盖）
4. 导入预览**零写入**（测试用 `StudentRecord.objects.count()` 前后对比）
5. 教师不能新建组织、不能导入、不能编辑学生（403）

## R5 教学（U4）⬜

待做：学年/学期/课程/教学班表单、任课分配、选课/退选、三角色 E2E。

## R6 审批（U5）⬜

待做：定义/版本表单、DEMO_ONLY 流程、提交/审批/驳回/撤回 UI、通知状态。

## R7 分析（U6）⬜

待做：看板筛选、图表、报表页、授权导出。

## 通用交互约定

| 约定 | 实现 |
|---|---|
| 提交防重复 | `form[data-sm-form]` 自动禁用按钮 + spinner |
| 危险操作确认 | `[data-sm-confirm]` + `data-sm-danger="1"` |
| 成功反馈 | `django.contrib.messages` + PRG 重定向 |
| 失败反馈 | 顶部 `#form-error` + 行内 `sm-error` |
| 并发冲突 | HTTP 409 + 明确文案 + 回填最新版本号 |

## R5 教学（U4）✅

| 操作 | 路由 | 角色 | 服务 | 关键校验 |
|---|---|---|---|---|
| 学年新建 | `/r5/years/new/` | system_admin | `create_year` | 日期倒置拒绝 |
| 学期新建 | `/r5/terms/new/` | system_admin | `create_term` | **超出学年范围 -> DATE_RANGE** |
| 课程新建 | `/r5/courses/new/` | system_admin | `create_course` | 编码唯一、学分数字 |
| 教学班新建 | `/r5/sections/new/` | system_admin | `create_section` | 同课程同班号唯一 |
| 任课分配 | `/r5/sections/<pk>/assign/` | admin/college | `assign_teacher` | 重复分配拒绝、撤销即失效 |
| 名册 | `/r5/sections/<pk>/roster/` | 任课教师/管理员 | `section_roster` | 他人 403 |
| 选课/退选 | `/r5/enroll/` | student | `enroll`/`drop` | 容量满、重复选课 |

## R6 审批（U5）✅

| 操作 | 路由 | 角色 | 服务 | 关键校验 |
|---|---|---|---|---|
| 定义新建 | `/r6/definitions/new/` | admin/college | `create_definition`+`add_node`+`add_transition`+`publish_version` | 模板生成、DEMO_ONLY 标注 |
| 定义详情 | `/r6/definitions/<pk>/` | admin/college | `active_version` | 展示节点/转移/版本 |
| 发起流程 | `/r6/instances/new/` | staff | `start_instance` | 必须有生效版本 |
| 实例详情 | `/r6/instances/<pk>/` | 创建者/管理员 | `transition` | 非创建者 403 |
| 执行动作 | `/r6/instances/<pk>/action/` | 同上 | `transition` | 非法动作 -> 错误、终态无按钮 |
| 待办完成 | `/r6/tasks/<pk>/complete/` | staff | `complete_task` | 重复完成 -> 提示 |
| 消息已读 | `/r6/notifications/<pk>/read/` | 本人 | `mark_read` | 他人 404 |

**R6 审计**：每次 `transition` 写 `WorkflowEvent`（action/from/to/actor/reason）；
端到端测试断言 `['create','submit','approve','approve']` 全部有 actor。
## R7 分析（U6）✅

| 操作 | 路由 | 角色 | 服务 | 关键约束 |
|---|---|---|---|---|
| 看板 | `/r7/dashboard/` | staff | `compute_metric` | KPI 卡 + 数据源筛选；抑制显示「已抑制」 |
| 指标注册表 | `/r7/metrics/` | staff | — | 指标 + 报表 + 最近运行 |
| 报表运行 | `/r7/reports/<code>/` | 按 permission_roles | `run_report` | 显示 query_hash/scope_hash |
| 报表导出 | `/r7/reports/<code>/export/` | 同上 | `export_report_csv` | CSV + `X-Query-Hash` |
| 快照序列 | `/r7/metric-series/` | 同上 | `MetricSnapshot` | 只读已存快照，不重算 |

**抑制不泄漏（测试锁定）**：
- HTML 中抑制指标渲染 `已抑制` 徽章，**不含数值节点** `id="value-<code>"`
- JSON 中 `value == 0` 且 `suppressed == true`
- CSV 中数值列为 `0`
- 真实值仅在服务端计算，从不下发

**scope 先于聚合（测试锁定）**：
- A 院管理员看到 8（本院），B 院看到抑制（2 < 阈值 5），系统管理员看到 10
- 三者的 `scope_hash` 互不相同
## R8 API 文档（U7）✅

| 项 | 实现 | 测试 |
|---|---|---|
| 端点表 | 从 `openapi_schema()` 动态生成，与真实路由**逐条比对** | `test_docs_lists_every_real_endpoint` |
| scope 说明 | 列出全部 5 个 scope，明写"默认没有任何 scope" | `test_docs_shows_all_scopes` |
| 不泄漏令牌 | 创建服务账号后，页面不含明文与摘要 | `test_docs_does_not_leak_tokens` |
| 环境标识 | "隔离演示环境 / 合成数据 / 未接外部系统" | `test_docs_marks_isolated_environment` |
| 权限 | staff-only；学生/匿名 403 | 3 例 |

## R9 运维状态（U7）✅

| 项 | 实现 | 测试 |
|---|---|---|
| 就绪探针 | database + migrations 明细 | `test_status_shows_readiness_checks` |
| 延迟分位 | P50/P95/P99 | `test_status_shows_latency_percentiles` |
| 告警规则 | 阈值/窗口/触发状态 | 页面渲染 |
| STAGING 标识 | "非生产环境，不承载真实数据" | `test_status_shows_staging_label` |
| 只读性 | 断言无 `method="post"`、无 `max_connections`、无"重启" | `test_status_has_no_write_actions` |
| 不泄漏 | 断言无 password / mysql:// | `test_status_does_not_leak_secrets` |

## API 不变量回归（U7 不得破坏）✅

| 不变量 | 测试 |
|---|---|
| scope 强制（有 read:units 无 read:students → 403） | `test_scope_still_enforced` |
| 默认空 scope | `test_default_scope_is_empty` |
| `read:students` ≠ 全校 | `test_read_students_does_not_mean_whole_school` |
| 限流 429 | `test_rate_limit_still_enforced` |
| 幂等重放 | `test_idempotency_still_enforced` |
| 令牌不存明文 | `test_token_not_stored_in_plaintext` |