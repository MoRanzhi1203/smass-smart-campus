# SMASS R10 UI/UX E2E 报告（U8）

- 设置：`smass.settings_r10`　库：`smass_r10_release`（隔离，合成数据）
- 基线 SHA：`5b69d58`
- 测试命令：
  ```powershell
  $env:R10_BROWSER='all'
  conda run -n smass python manage.py test smass_operations.tests.test_r10_u8_browser --settings=smass.settings_r10
  conda run -n smass python scripts/r10_browser_probe.py   # 真实服务器三引擎
  ```

## 1. 结果总览

| 套件 | 用例 | 引擎 | 结果 |
|---|---|---|---|
| `test_r10_u8_routes.py` | 21 | —（Django Client） | **PASS** |
| `test_r10_u8_browser.py` | 42 | Chromium / Firefox / WebKit | **PASS** |
| `scripts/r10_browser_probe.py` | 3 引擎 × 11 步 | 真实 runserver | **ok: true** |

## 2. 跨模块业务旅程（每步断言 DB）

`SilentJourneyTests::test_full_journey_persists_each_step`：

| 步骤 | 动作 | DB 断言 |
|---|---|---|
| R4 | 创建学院 + 专业 | `OrganizationUnit.objects.get(code='U8-COL')` 存在；`major.parent == college` |
| R4 | CSV 导入 2 名学生 | `StudentRecord.filter(student_no__startswith='U8S').count() == 2` |
| R5 | 建学年 / 学期 / 课程 / 教学班 | 各对象可 `get()`；`section.term.year.code == 'U8-Y'` |
| R5 | 分配教师 | `academic_services.can_teach(teacher, section) is True` |
| R6 | 建流程 / 发起 / 提交 / 审批 | `instance.status` 依次 `draft → pending → approved` |
| R7 | 计算指标 | `int(value) == OrganizationUnit.objects.count()` |
| R8 | 打开 API 文档 | 页面含 `/api/v1/units/` |
| R9 | 打开运维页 | 页面含 `id="probe-table"` |

`test_journey_survives_reload`：写入后重新 GET 列表页，数据仍在（排除内存假象）。

## 3. 浏览器级提交流程（Chromium + Firefox）

| 测试 | 验证 |
|---|---|
| `test_01_create_org_via_browser` | 填表单 → 点保存 → **`OrganizationUnit` 真的存在** |
| `test_02_org_form_validation_shown` | 空编码 → 页面出现"编码不能为空"且**未写库** |
| `test_03_import_preview_then_commit` | 预览后**零写入**；浏览器内 POST 后**写入 1 条** |
| `test_04_workflow_create_and_approve` | 建流程 → 发起 → 提交 → `instance.status == 'pending'` |
| `test_05_dashboard_shows_data` | 看板渲染 KPI 且含真实指标码 |
| `test_06_api_docs_and_ops_pages` | 两个页面内容正确 |

## 4. 三引擎矩阵

| 能力 | Chromium | Firefox | WebKit |
|---|---|---|---|
| 匿name 登录页 / 首页渲染 | ✅ | ✅ | ✅ |
| 真实表单登录 | ✅ | ✅ | ⚠️ 见 §5 |
| 组织创建（写入 DB） | ✅ | ✅ | — |
| 导入预览 + 提交（写入 DB） | ✅ | ✅ | — |
| 流程发起 + 审批（状态机） | ✅ | ✅ | — |
| 响应式无溢出（1280/768/390） | ✅ | ✅ | ✅（首页） |
| 移动抽屉开/关 + Escape | ✅ | ✅ | ✅（真实服务器探针） |
| 键盘可达 + 焦点可见 | ✅ | ✅ | — |
| **真实服务器完整流程** | ✅ | ✅ | ✅ |

## 5. WebKit 的真实限制（不掩饰）

**现象**：在 Django `LiveServerTestCase`（WSGI 线程服务器）下，WebKit 的
`POST /r21/login/` 返回 **500**：

```
django.db.utils.DatabaseError: Save with update_fields did not affect any rows.
```

**对照实验**：

| 环境 | Chromium | Firefox | WebKit |
|---|---|---|---|
| `LiveServerTestCase`（随机端口 + 线程 WSGI） | 正常 | 正常 | **登录 500** |
| 真实 `runserver 8000` | 正常 | 正常 | **完全正常** |

**结论**：这是**测试基础设施**问题（与 R2.1 时观察到的 WebKit 竞态同源），
不是产品缺陷。真实部署用真实 WSGI 服务器，不受影响。

**处置**：
1. WebKit 在单测中只跑**匿名渲染 + 响应式 + reduced-motion**（4 例，全绿）；
2. 完整流程用 `scripts/r10_browser_probe.py` 在真实服务器上跑，三引擎 `ok: true`；
3. 不把 WebKit 的表单流程标为"通过"——它在单测环境下确实没通过。

## 6. 响应式验证

| 视口 | 检查 | 结果 |
|---|---|---|
| 1280×860 desktop | 7 页 `scrollWidth <= clientWidth + 1` | PASS |
| 768×1024 tablet | 同上 | PASS |
| 390×844 mobile | 同上 + 抽屉可用 | PASS |

抽屉行为（真实浏览器）：点击打开 → 遮罩出现 → `Escape` 关闭 → 焦点回触发按钮。

## 7. 静默旅程截图证据

`docs/screenshots/r10_uiux/` 下 u1–u7 共 **23 张**，覆盖：
导航、组织、学生、导入（含预览态）、教学班、任课分配、名册、流程定义（真实创建）、
看板、报表、API 文档、运维状态、移动抽屉。
