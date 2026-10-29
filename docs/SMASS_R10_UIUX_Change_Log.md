# SMASS R10 UI/UX 变更日志（U9）

基线：`5b69d58`　分支：`feat/smass-r4-r10-integrated-platform`

## 提交序列

| SHA | 类型 | 内容 |
|---|---|---|
| `f434d14` | chore | U0 基线审计、60 路由清单、账本、门禁 |
| `56dc6aa` | feat | U1+U2 统一外壳（侧边栏/抽屉）、设计系统 |
| `c73fd12` | chore | U1/U2 账本更新 |
| `e56ee46` | feat | U3 R4 组织与学生表单、409 冲突、导入向导 |
| `ce73c13` | feat | U4 R5 教学表单、任课分配、名册、选课 |
| `377224d` | feat | U5 R6 流程模板、状态机、待办、通知 |
| `5525f69` | feat | U6 R7 看板筛选、报表、导出、抑制不泄漏 |
| `43f2b11` | feat | U7 R8 文档 + R9 运维 + 权限矩阵 |
| `3b20174` | feat | U8 跨模块 E2E、三引擎、响应式、可访问性 |
| 本提交 | feat | U9 全量回归、5 份文档、最终验收 |

## 新增文件

### 设计系统
- `static/css/r10.css` — 设计令牌 + 13 类组件 + 响应式断点 + 打印 + reduced-motion
- `static/js/r10.js` — toast / Promise 化 confirm / CSRF request / 提交防重 / 抽屉与焦点陷阱

### 视图（新增）
- `smass_organization/ui_views.py` — 组织新建/编辑、学生详情/编辑、导入提交
- `smass_academic/ui_views.py` — 学年/学期/课程/教学班表单、任课、名册、选课
- `smass_workflow/ui_views.py` — 流程模板、定义详情、实例、待办、通知
- `smass_analytics/ui_views.py` — 看板、指标报表、报表详情、导出、快照序列
- `smass_operations/ui_views.py` — 导入页、API 文档、运维状态

### 模板（新增 24 个）
`r4/unit_form.html` `r4/student_detail.html` `r4/student_form.html` `r4/import.html`
`r5/year_form.html` `r5/term_form.html` `r5/course_form.html` `r5/section_form.html`
`r5/section_assign.html` `r5/roster.html` `r5/enroll.html`
`r6/definition_new.html` `r6/definition_detail.html` `r6/instance_new.html` `r6/instance_detail.html`
`r7/report_detail.html`
`r8/docs.html` `r9/status.html`
`r10/base.html`（重写）`r10/home.html`（重写）
+ 14 个既有模板改造为继承新外壳

### 脚本
- `scripts/r10_ui_inventory.py` — 路由自动枚举
- `scripts/r10_uiux_gate.py` — 账本门禁（结构 + 证据 + 依赖顺序）
- `scripts/r10_demo_seed.py` — 幂等演示数据（含 DEMO-RPT 报表）
- `scripts/r10_screenshot.py` — 截图
- `scripts/r10_browser_probe.py` — 真实服务器三引擎探针

### 测试（新增 10 个文件）
- `test_r10_shell.py`（15）
- `test_r10_nav.py`（6，已对齐新契约）
- `test_r10_u3_r4.py`（24）
- `test_r10_u4_r5.py`（26）
- `test_r10_u5_r6.py`（23）
- `test_r10_u6_r7.py`（24）
- `test_r10_u7_r8r9.py`（26）
- `test_r10_u8_routes.py`（21）
- `test_r10_u8_browser.py`（42，三引擎）
- `test_r10_release.py`（10，已对齐新契约）

## 修复的真实缺陷（按发现顺序）

| # | 缺陷 | 根因 | 修法 |
|---|---|---|---|
| 1 | 组织表单重复编码 500 | `create_unit` 的 `IntegrityError` 未捕获，事务被污染 | `with transaction.atomic()` + 友好文案 |
| 2 | 学生编辑不生效 | `editable_fields()` 返回 `StudentFieldDefinition` 对象而非字段名 | 新增 `_base_editable()` 按角色判定 |
| 3 | 学生编辑 500 | `update_student` 返回 `(record, changes)` 被当单值 | 正确解包 |
| 4 | 导入提交 500 | `import_commit` 返回 `(job, stats)` 被当 preview list | 正确解包 |
| 5 | 组织表单 500 | `errors.__all__` 在 Django 模板非法 | 改 `errors.general` |
| 6 | 学生详情页不生效 | `<str:student_no>` 旧路由抢占 | 新路由注册在 `r4_patterns` 之前 |
| 7 | 导入预览 404/走错视图 | 同上 | 同上 |
| 8 | 实例发起只报第一个错误 | `elif` 链 | 改独立 `if` |
| 9 | 首页无导航高亮 | 无 `/r10/` 匹配项 | 新增"概览"条目 |
| 10 | `/r4/import/` 双高亮 | `/r4` 前缀匹配过宽 | 精确匹配 `/r4/units` |
| 11 | 选课页 500 | `student_sections()` 返回 Section，模板用了 `enrollment_pk` | 视图建 `enrollment_by_section` 映射 |
| 12 | 列表页无"新建"入口 | 只做了表单页没连线 | 4 个列表页加按钮 + 教学班加操作列 |
| 13 | 演示 seed 不幂等 | `create_unit`/`assign_teacher`/`enroll` 重复抛错 | `get_or_create` + `try/except` |
| 14 | WebKit 单测登录 500 | `Save with update_fields did not affect any rows`（测试服务器线程） | WebKit 只跑匿名渲染；真实服务器探针覆盖 |
| 15 | **U6 改模板未改旧视图（U9 回归发现）** | `urls_r7` 用旧 `dashboard`，模板已改 | 旧视图补 `code`/`description`/`unit` 等字段 |
| 16 | **JSON 响应缺 `metric` 键（U9 回归发现）** | 新结构只给 `code`，旧浏览器测试依赖 `metric` | 同时提供两个键 |
| 17 | 演示口令硬编码 3 处 | 脚本内联 | 改 `SMASS_DEMO_PASSWORD` 环境变量 + 白名单 |

## 破坏性变更

**无。** 所有改动都在 `smass_r*` 隔离库与 `smass/settings_r*.py`；
`AUTH_USER_MODEL`、`app01`、正式 `smass` 数据库零改动。

## 已知未实现（原样记录）

| 项 | 原因 |
|---|---|
| 真实改密页 | 列为风险 R-03 |
| 成绩管理 | BD-05 未批准 |
| 正式审批链 | BD-06 未提供 |
| 官方 KPI 口径 | BD-07 未提供 |
| 屏幕阅读器实机验证 | 需人工 + 真实 AT |
| 完整 WCAG 审计 | 需专业工具与人工 |
| 文件上传导入（Excel） | 演示范围外 |
