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