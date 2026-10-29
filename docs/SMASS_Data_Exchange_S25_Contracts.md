# SMASS S25 — 统一 Excel/CSV 数据交换中心

状态：**引擎 `TESTED` · R4 适配器 `TESTED` · R5 适配器 `PENDING` · CSV 性能 `PENDING`**

---

## 1. 交付形态

新增纯 Python 包 `smass_data_exchange/`（**不新增任何模型/迁移**，对正式库零影响）：

| 文件 | 职责 |
|---|---|
| `schema.py` | 版本化字段定义 `FieldSpec` / `DatasetSchema` + 注册表 + 值规范化 |
| `templates.py` | 生成真实 `.xlsx`（Data/Instructions/Options）与 UTF-8 BOM `.csv` |
| `parsing.py` | 上传解析（xlsx/csv、编码、压缩炸弹、行数/字节上限） |
| `service.py` | 预检（零写入）、签名令牌、提交（幂等）、错误工作簿 |
| `export.py` | 安全导出（字段级裁剪 + 公式注入中和） |
| `adapters.py` | 业务适配器（当前 R4 学生档案） |
| `views.py` | HTTP 层：模板下载 / 上传 / 预检 / 提交 / 错误 / 历史 / 导出 |
| `templates/exchange/*.html` | 可见页面 |

**不建表的好处**：正式 `smass` 库保持只读时，引擎仍可部署与演练；
业务记录复用 R4 既有的 `DataImportJob` / `DataImportRowError`。

## 2. 单一 schema 来源

```python
FieldSpec(code, label, required, dtype, max_length, choices, help, example, sensitive)
DatasetSchema(code, version, title, fields, instructions, notes)
```

- 模板表头、解析校验、导出列、错误工作簿指引**全部**由同一 schema 生成；
- `schema.signature()` 把 code/version/引擎版本/字段签名哈希，供令牌绑定；
- 版本不同不允许静默替换（`register()` 会抛错）。

## 3. 真实模板

### 3.1 Excel（`.xlsx`）

三张表，实测结构：

```
sheetnames == ['Data', 'Instructions', 'Options']
```

- `Data`：表头（必填列带 `*`）+ **第 2 行灰色示例**（导入时自动忽略）+ 枚举下拉校验；
- `Instructions`：字段/中文名/必填/类型/长度/可选值/说明/示例，末尾附数据集、模板版本、导入说明；
- `Options`：枚举字段的取值清单（供下拉引用）。

示例值全部为构造值（`DEMO-1001` / `演示学生A` / `DEMO-K` / `2024-09-01`），
测试断言示例行**不含**手机号或身份证格式。

### 3.2 CSV（`.csv`）

- UTF-8 **BOM**（`utf-8-sig`），Excel 双击中文不乱码；
- 表头与 `Data` 一致；一行示例；
- 文件名 ASCII：`smass_template_r4_students_v1.csv`。

## 4. 上传与解析

| 防护 | 实现 |
|---|---|
| 类型白名单 | 只接受 `.xlsx` / `.csv`；`.xls/.xlsm/.ods` 拒绝 |
| 扩展名与魔数矛盾 | `.xlsx` 但不是 zip → 拒绝；`.csv` 但是 zip → 拒绝 |
| 压缩炸弹 | 解压总量 ≤ 64 MB，压缩比 ≤ 120:1 |
| 公式不执行 | `load_workbook(read_only=True, data_only=True)` |
| 字节上限 | 8 MB（`MAX_UPLOAD_BYTES`） |
| 行数上限 | 5000（`MAX_ROWS`） |
| 编码 | 依次尝试 `utf-8-sig` → `utf-8` → `gb18030`；全失败即报错，**不做 replace 静默降级** |
| 缺列 | `MISSING_COLUMN`，提示使用模板 |
| 未知列 | 记录在 `meta.unknown_columns`，不阻断（模板演进友好） |

## 5. 预检零写入 + 令牌防 TOCTOU

`preview()` **不写任何数据库记录**（测试断言 `StudentRecord` 与 `DataImportJob` 数量不变）。

返回：

```json
{"ok":..., "ticket":"...", "summary":{total,ok,errors,would_create,would_update,would_skip},
 "errors":[{"row","column","code","message"}], "diff":[{...}], "meta":{...}}
```

令牌 = `signing.dumps({数据集, schema版本, 引擎版本, 文件SHA256, 操作者, 签发时间})`，30 分钟有效。

`commit()` 的六道校验（任一失败即 409）：

| 校验 | 错误码 |
|---|---|
| 签名有效 | `TICKET_BAD_SIGNATURE` |
| 未过期 | `TICKET_EXPIRED` |
| 数据集一致 | `TICKET_DATASET_MISMATCH` |
| schema 版本未变 | `TICKET_SCHEMA_CHANGED` |
| 引擎版本未变 | `TICKET_ENGINE_CHANGED` |
| 操作者一致 | `TICKET_ACTOR_MISMATCH` |
| **文件摘要一致** | `TICKET_DIGEST_MISMATCH` |

并且提交时**重新解析、重新校验**，不信任预检阶段提交的行数据。

## 6. 提交幂等

- 默认 `allow_partial=False`：只要存在错误行就**整体拒绝**，避免"一半进一半不进"；
- 无变化行记为 `skip`，重复提交同一文件第二次 `created=0, skipped=N`（有测试）；
- 数据库唯一约束（`StudentRecord.student_no`）是最后一道防线；
- 更新走版本号 +1 与 `StudentRecordChange` 追加历史，不原地覆盖。

## 7. 错误工作簿与导入历史

- 失败提交也会创建 `DataImportJob`（`status=failed`）并落 `DataImportRowError`；
- `GET /exchange/errors/<dataset>/<job_id>/` 下载 `.xlsx`：`Errors` 表（行号/列/错误码/说明）+ `Guide` 表（字段指引，便于直接修正重传）；
- 错误消息也做公式注入中和；
- `GET /exchange/history/<dataset>/` 展示最近 50 个批次（含失败），可直接下载错误。

## 8. 安全导出

- 字段级裁剪：`allowed_codes` 由 `r21_account.authorization.visible_fields()` 决定；
- 公式注入中和：`= + - @ \t \r \n` 开头的文本前加单引号；
- `sensitive=True` 的字段默认掩码（`139******22`）；
- 导出需 `export` 动作权限（学生角色被拒，实测 403）；
- 文件名 ASCII。

## 9. 可见业务流程（强制项）

页面 `/exchange/` → `/exchange/import/r4_students/`：

```
下载 Excel/CSV 模板  →  选择文件  →  上传并预检  →  查看汇总/差异/错误
                    →  确认导入  →  结果（新增/更新/跳过/冲突）  →  错误下载 / 导入历史
```

HTTP 端点：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/exchange/` | 数据集列表 |
| GET | `/exchange/template/<ds>/?fmt=xlsx\|csv` | 模板下载 |
| GET | `/exchange/import/<ds>/` | 导入页（表单） |
| POST | `/exchange/preview/<ds>/` | 预检（JSON） |
| POST | `/exchange/commit/<ds>/` | 提交（JSON） |
| GET | `/exchange/errors/<ds>/<job_id>/` | 错误工作簿 |
| GET | `/exchange/history/<ds>/` | 导入历史（HTML/JSON） |
| GET | `/exchange/export/<ds>/` | 安全导出 |

## 10. 验收证据

### 10.1 引擎测试 `tests/test_s25_roundtrip.py` — 40 例

```
python manage.py test smass_data_exchange --settings=smass.settings_r4
Ran 40 tests in 23.730s
OK   exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `TemplateTests` | 7 | 三表结构、表头一致、示例为合成值、Instructions 列全字段、CSV BOM、文件名 ASCII、非法格式 |
| `ParsingTests` | 9 | 魔数判定、伪 xlsx、非法扩展名、超大、缺列、坏编码、示例行跳过、非法枚举、GBK 解码、zip 炸弹 |
| `PreviewTests` | 6 | **零写入**、未知组织、文件内重复、update 判定、skip 判定、无权限拒绝 |
| `TicketTests` | 4 | 令牌往返、篡改、摘要不符、操作者不符 |
| `CommitTests` | 5 | 创建、**幂等**、更新、有错误时整体拒绝、CSV 往返 |
| `ErrorBookAndExportTests` | 5 | 错误工作簿内容、错误工作簿中和、导出中和、字段裁剪、ASCII 文件名 |
| `SchemaTests` | 3 | 未知数据集、重复字段、enum 缺 choices |

### 10.2 HTTP 层测试 `tests/test_s25_ui.py` — 18 例

```
python manage.py test smass_data_exchange.tests.test_s25_ui --settings=smass.settings_r4
Ran 18 tests in 25.874s
OK   exit 0
```

覆盖：模板下载（xlsx/csv/BOM/版本头/非法格式/未知数据集）、首页与导入页元素、
预检端点（含零写入断言）、提交完整旅程、缺令牌 400、**换文件用旧令牌 409**、
失败批次建作业 + 错误工作簿下载（断言 `UNKNOWN_UNIT` 在表内）、历史 HTML/JSON、
导出中和、匿名跳登录、无导入权限拒绝、无导出权限 403。

### 10.3 模块级回归

```
python manage.py test smass_data_exchange smass_organization --settings=smass.settings_r4
Ran 127 tests in 209.830s
OK   exit 0
```

（S25 58 + R4 69）

### 10.4 真实模板往返（非模拟）

`test_commit_endpoint_full_journey` 的实际步骤：

1. `build_xlsx_template()` 生成字节 → 存为上传文件；
2. 用 `openpyxl` 打开该字节、**删除示例行、按表头写入两行数据**（即"用户在 Excel 里填写"）；
3. `POST /exchange/preview/` → 断言 `would_create == 2` 且数据库零变化；
4. `POST /exchange/commit/`（携带同一令牌与文件）→ 断言 `created == 2`；
5. 断言 `StudentRecord.objects.filter(student_no='UI2001').exists()`。

## 11. 未完成（诚实标注）

| 项 | 状态 | 说明 |
|---|---|---|
| **R5 适配器**（学年/学期/课程/教学班/选课） | `PENDING` | 引擎已具备；需在 `smass_academic` 上实现第二个适配器 |
| CSV 导出性能优化（12.5s/10k） | `PENDING` | `S25-PERF` 任务，需实测基线对比 |
| 异步作业（超大批次） | `PENDING` | 当前同步处理；上限 5000 行已能覆盖常规场景 |
| 浏览器级 E2E（Playwright） | `PENDING` | 本轮以 HTTP 层全链路替代；浏览器烟测留待 `tests_e2e` 扩展 |
| 真实人员数据导入 | `BLOCKED_EXTERNAL_AUTH` | 需数据授权；当前全部合成数据 |

## 12. 安全性声明

- 引擎无模型、无迁移 → 正式库结构不变；`smass` 库 **0 写入**。
- 预检零写入；提交需令牌，且令牌与文件摘要/操作者/版本绑定。
- 公式注入在导出与错误工作簿两处都中和。
- 未处理任何真实个人数据；模板示例全为构造值。
- 所有上传端点要求登录 + `import` 动作权限（默认拒绝）。
