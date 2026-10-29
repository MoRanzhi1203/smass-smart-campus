# SMASS S25-R4 — 学生档案导入适配器与模板索引

状态：**`TESTED`** · 数据集 `r4_students` · 模板版本 `v1`

---

## 1. 适配器位置与职责

`smass_data_exchange/adapters.py::R4StudentAdapter`

| 方法 | 职责 |
|---|---|
| `validate(rows, account)` | 组织编码存在性、文件内学号重复、库内唯一性、学籍状态合法性、导入权限；产出每行 `__plan__`（create/update/skip） |
| `commit(validated, account)` | 单事务写 `StudentRecord`，追加 `StudentRecordChange`，更新 `DataImportJob` |
| `describe_row(row, account)` | 预检差异预览（已裁剪字段） |

复用而非重写：
- 模型：`OrganizationUnit` / `StudentRecord` / `StudentRecordChange` / `DataImportJob` / `DataImportRowError`
- 权限：`r21_account.authorization.has_action(account, 'import')`
- 状态取值：直接取自 `StudentRecord.status.field.choices`（不硬编码）

## 2. 模板索引

| 数据集 | 标题 | 版本 | Excel | CSV | 必填列 |
|---|---|---|---|---|---|
| `r4_students` | 学生档案导入（R4） | v1 | `smass_template_r4_students_v1.xlsx` | `smass_template_r4_students_v1.csv` | `student_no`、`name` |

### 字段定义

| 字段 | 中文名 | 必填 | 类型 | 说明 | 模板示例（合成） |
|---|---|---|---|---|---|
| `student_no` | 学号 | 是 | str(20) | 唯一；文件内不可重复 | `DEMO-1001` |
| `name` | 姓名 | 是 | str(32) | 真实使用时须用授权数据 | `演示学生A` |
| `unit_code` | 组织编码 | 否 | str(64) | 必须已存在，否则 `UNKNOWN_UNIT` | `DEMO-K` |
| `status` | 学籍状态 | 否 | enum | 取自模型 choices；留空默认 `enrolled` | `enrolled` |
| `enrolled_at` | 入学日期 | 否 | date | `YYYY-MM-DD`（也接受 `YYYY/MM/DD`、`YYYYMMDD`） | `2024-09-01` |

Excel 结构：`Data`（表头 + 灰色示例 + 枚举下拉）/ `Instructions`（字段表 + 版本 + 说明）/ `Options`（枚举清单）。
CSV：UTF-8 BOM，表头 + 一行示例。

## 3. 错误码

| 错误码 | 含义 | 修复方式 |
|---|---|---|
| `EMPTY_STUDENT_NO` | 学号为空 | 填学号 |
| `DUPLICATE_IN_FILE` | 文件内学号重复 | 去重 |
| `EMPTY_NAME` | 姓名为空 | 填姓名 |
| `INVALID_STATUS` | 非法学籍状态 | 用 `Options` 表取值 |
| `UNKNOWN_UNIT` | 组织编码不存在 | 先建组织，或改正编码 |
| `PERMISSION_DENIED` | 无 `import` 动作权限 | 申请权限 |
| `VANISHED` | 预检后记录被删除（提交期竞态） | 重新预检 |
| `MISSING_COLUMN` / `TOO_LARGE` / `TOO_MANY_ROWS` / `BAD_ENCODING` / `ZIP_BOMB` | 文件级拒绝 | 按提示修正/拆分/另存 |

## 4. 真实往返验证（实测）

```python
# 1) 用引擎生成模板
template = build_xlsx_template(get('r4_students'))
# 2) 用 openpyxl 打开、删除示例行、按表头写入两行（模拟用户填写）
# 3) POST /exchange/preview/r4_students/  -> would_create == 2，数据库零变化
# 4) POST /exchange/commit/r4_students/   -> created == 2
# 5) StudentRecord.objects.filter(student_no='UI2001').exists() == True
```

对应测试：

- `smass_data_exchange/tests/test_s25_roundtrip.py::CommitTests`（引擎级）
- `smass_data_exchange/tests/test_s25_ui.py::VisibleFlowTests::test_commit_endpoint_full_journey`（HTTP 级）

## 5. 与既有 R4 文本导入的关系

R4 原有 `services.import_preview/import_commit`（**粘贴 CSV 文本**）保持不动，
既有测试与页面继续可用。S25 提供的是**文件上传 + 模板下载**的等价通道，
两者最终写入同一批模型，因此不存在"两套导入逻辑写出不同结果"的风险。

> 后续可考虑把 R4 原有文本导入改为委托 S25 引擎；本轮不做，以避免无收益的重构。

## 6. 证据

```
python manage.py test smass_data_exchange --settings=smass.settings_r4
Ran 40 tests in 23.730s   OK

python manage.py test smass_data_exchange.tests.test_s25_ui --settings=smass.settings_r4
Ran 18 tests in 25.874s   OK

python manage.py test smass_data_exchange smass_organization --settings=smass.settings_r4
Ran 127 tests in 209.830s OK
```

## 7. 未完成

| 项 | 状态 |
|---|---|
| 学生档案导出接入 S25 `export_dataset`（当前 R4 已有自己的 CSV 导出） | 可选，未做 |
| 组织单元（college/major/class）批量导入适配器 | `PENDING`（当前仅学生档案） |
| 真实人员数据导入 | `BLOCKED_EXTERNAL_AUTH` |
