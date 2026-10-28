# SMASS R4 交付报告（组织机构与学生档案）

- 分支：`feat/smass-r4-r10-integrated-platform`
- 隔离库：`smass_r4_org`（全合成）
- 配置：`smass/settings_r4.py`、`smass/urls_r4.py`
- **状态：CORE_COMPLETE / PARTIAL**（核心能力可用；E2E 与组织级 scope 未完成）

## 1. 实际交付

### 1.1 数据模型（7 个，迁移 `0001_initial`）

| 模型 | 作用 |
|---|---|
| `OrganizationUnit` | 组织树（类型/父节点/状态/排序/有效期），父子类型受控 |
| `OrganizationMembership` | 人员-组织多归属（条件唯一：未结束的关系） |
| `StudentRecord` | 学籍档案（学号唯一、关联 Account、乐观锁 `version`） |
| `StudentRecordChange` | 变更历史（append-only，带 `batch_id`） |
| `StudentFieldDefinition` | 字段字典（B 类可配置：敏感标记、可见/可编辑角色） |
| `DataImportJob` | 导入批次（UUID、状态、行数统计） |
| `DataImportRowError` | 导入错误行（行号/列/错误码） |

### 1.2 服务层（`smass_organization/services.py`）

| 能力 | 实现 |
|---|---|
| 组织类型约束 | `ALLOWED_CHILDREN` 白名单（college→major/grade、major/grade→class 等） |
| 防环 | 移动时沿父链回溯检测，**环优先于类型错误判定** |
| 移动审计 | `audit.record_success('org_unit_moved')` |
| 字段级权限 | `visible_fields` / `editable_fields` / `filtered_extra` |
| 导入预检 | CSV 解析 + 逐行校验（空学号/文件内重复/非法状态/未知组织） |
| 导入提交 | 逐行 upsert + 变更历史；单行失败不阻断整批 |

### 1.3 视图与页面（8 个端点 + 2 个模板）

| 端点 | 方法 | 权限 |
|---|---|---|
| `/r4/health/` | GET | 公开 |
| `/r4/units/` | GET | teacher/college_admin/system_admin |
| `/r4/units/tree/` | GET | 同上 |
| `/r4/units/create/` | POST | **system_admin** |
| `/r4/units/<pk>/move/` | POST | **system_admin** |
| `/r4/students/` | GET | teacher 及以上（字段级过滤） |
| `/r4/students/<student_no>/` | GET | 同上（含历史） |
| `/r4/import/preview/`、`/r4/import/commit/` | POST | **system_admin** |

模板：`templates/r4/unit_list.html`、`templates/r4/student_list.html`（真实渲染，非占位）。

## 2. 测试（23 例，全 PASS）

| 类 | 用例 | 覆盖 |
|---|---|---|
| `OrganizationTreeTests` | 6 | 合法创建、非法层级、**成环拒绝**、移到自己、合法移动、重复编码 |
| `FieldPermissionTests` | 5 | 管理员可见敏感字段、教师不可见、公开字段、`extra` 裁剪、匿名仅公开 |
| `ImportTests` | 5 | 预检不写库、提交建档案+历史、更新并记变更、缺列快速失败、重复学号不重复建 |
| `ViewPermissionTests` | 7 | 匿名 403、无角色 403、列表渲染、详情 JSON、创建、**成环返回 400 CYCLE**、health |

真实命令：`manage.py test smass_organization --settings=smass.settings_r4` → **23/23 OK**（18.43 s）。

## 3. 过程中修复的真实缺陷

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | 类型校验先于成环校验，导致"把学院移到自己的班级下"被报成 `INVALID_HIERARCHY` 而非 `CYCLE` | 调整判定顺序：**环优先** |

这不是为了让测试通过而改断言——而是错误分类的正确性：环是更严重且更具体的错误。

## 4. 未完成（如实标注）

| 项 | 状态 | 说明 |
|---|---|---|
| 组织级数据 scope（学院管理员只看本院） | **NOT DONE** | 字段级已有；组织级过滤未实现 |
| 浏览器 E2E | **NOT DONE** | 只有 Django Client 测试 |
| 并发更新冲突测试 | **NOT DONE** | `version` 字段已备，未测并发覆盖 |
| 导出（受限导出） | **NOT DONE** | 只做导入 |
| 真实学校字段清单 | **BUSINESS_CONFIG_PENDING** | 字段字典是通用骨架，具体字段待定 |

## 5. 安全边界

| 项 | 状态 |
|---|---|
| `smass` 写入 | **NONE** |
| `app01` 修改 | 无 |
| `AUTH_USER_MODEL` | 未改 |
| 数据 | 全合成（`R4S001` 等） |
| 新增库 | `smass_r4_org`（保留） |

## 6. 结论

R4 的**组织树 + 字段级权限 + 导入**是可用的真实能力，23 例测试通过。
但**未达到计划要求的完整验收**（缺组织级 scope、浏览器 E2E、并发测试），
因此标 `CORE_COMPLETE / PARTIAL`，不标 `TESTED`，更不标 `RELEASED`。
