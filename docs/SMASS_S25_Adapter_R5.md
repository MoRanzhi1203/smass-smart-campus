# SMASS S25-R5 — 学年/学期/课程/教学班/选课 导入适配器

状态：**`TESTED`** · 数据集 5 个 · 模板版本均 `v1`

---

## 1. 交付内容

`smass_data_exchange/adapters_r5.py`，五个数据集：

| 数据集 code | 标题 | 必填列 | 关键外键/规则 |
|---|---|---|---|
| `r5_academic_years` | 学年导入 | `code`、`start_date`、`end_date` | 编码唯一；`end_date > start_date` |
| `r5_academic_terms` | 学期导入 | `year_code`、`semester`、`start_date`、`end_date` | 学年必须存在；`(学年,学期)` 文件内唯一 |
| `r5_courses` | 课程导入 | `code`、`title` | 编码唯一；学分 0<credit≤99.9 |
| `r5_sections` | 教学班导入 | `year_code`、`semester`、`course_code`、`code` | 学年+学期+课程必须存在；`(学期,班号)` 唯一；容量非负 |
| `r5_enrollments` | 选课导入 | `year_code`、`semester`、`section_code`、`login_name` | 教学班必须存在且 `status=open`；**容量校验**；账号必须存在 |

## 2. 枚举值来自模型，不硬编码

- 学期取值：`AcademicTerm.SEMESTER_CHOICES` → `('1','2','S')`
- 教学班状态：`TeachingSection.STATUS_CHOICES` → `('open','closed')`
- 选课状态：`Enrollment.STATUS_ENROLLED/STATUS_DROPPED`

> 实测踩到的坑：`SEMESTER_CHOICES` / `STATUS_OPEN` 是**类属性**（定义在模型类体内），
> 不是模块级常量。首版写 `from smass_academic.models import SEMESTER_CHOICES` 直接
> ImportError。已改为 `AcademicTerm.SEMESTER_CHOICES`，并加了
> `test_enum_choices_come_from_models` 断言取值集合，防止再退回硬编码。

## 3. 选课容量校验（核心业务规则）

`R5EnrollmentAdapter.validate()` 同时考虑：

1. 数据库里该教学班**已选人数**（`status != 'dropped'`）；
2. **同一文件内**已为其它行预留的名额（`reserved` 计数）。

```
若 section.capacity > 0 且 (已选 + 本文件已预留) >= capacity → 该行 SECTION_FULL
```

`capacity == 0` 表示不限制（与模型 `help_text` 一致）。

测试覆盖三种情形：

| 用例 | 场景 | 期望 |
|---|---|---|
| `test_capacity_full_rejected` | 容量 2，文件内 3 人 | 第 3 人 `SECTION_FULL` |
| `test_capacity_respects_existing_enrollments` | 库内已 1 人 + 文件 2 人，容量 2 | 第 2 个新增者 `SECTION_FULL` |
| `test_zero_capacity_means_unlimited` | 容量 0，文件 3 人 | 全部 `created=3` |

## 4. 幂等与状态恢复

| 情形 | 行为 |
|---|---|
| 学年/学期/课程/教学班 已存在且字段一致 | `skip`，不写库 |
| 已存在但字段有变 | `update`（教学班只更新 course/capacity/status） |
| 选课记录已存在且 `status=enrolled` | `skip` |
| 选课记录存在但 `status=dropped` | `update`：恢复为 `enrolled` 并写 `EnrollmentHistory` |
| 同一文件重复导入 | 第二次全部 `skip`（学年/课程各有测试） |

## 5. 错误码

| 错误码 | 含义 |
|---|---|
| `EMPTY_CODE` / `EMPTY_TITLE` / `EMPTY_YEAR` / `EMPTY_SEMESTER` / `EMPTY_LOGIN` | 必填为空 |
| `DUPLICATE_IN_FILE` | 文件内唯一键重复 |
| `UNKNOWN_YEAR` / `UNKNOWN_TERM` / `UNKNOWN_COURSE` / `UNKNOWN_SECTION` / `UNKNOWN_ACCOUNT` | 外键不存在 |
| `BAD_RANGE` | 结束日期不晚于开始日期 |
| `BAD_CREDIT` / `BAD_CAPACITY` | 数值越界或非数字 |
| `SECTION_FULL` | 容量已满（含文件内预留） |
| `SECTION_CLOSED` | 教学班状态非 `open` |
| `INVALID_VALUE` | 枚举/日期/长度等结构校验失败 |
| `PERMISSION_DENIED` | 无 `import` 动作权限 |

## 6. 环境差异（诚实标注）

`settings_r5` 继承 `settings_r4`，因此**同时**安装 `smass_organization` 与
`smass_academic`。这意味着：

- R5 的导入作业历史可用（复用 `DataImportJob`）；
- `r5` 与 `r4` 的 `smass_data_exchange` 测试互不跳过（两边 app 都齐）；
- 只有在**缺少**对应 app 的 settings 下，测试模块才会 `SkipTest`
  （`test_s25_r5.py` 检查 `smass_academic`，R4 两个文件检查 `smass_organization`）。

`_create_job()` 仍保留降级路径：若某环境只有 `smass_academic` 而没有
`smass_organization`，导入照常进行，只是没有作业历史。

## 7. HTTP 入口

`smass/urls_r5.py` 已挂载 S25 的 8 个端点（`/exchange/...`），
与 R4 完全一致；登录跳转目标由 `settings.LOGIN_URL` 决定
（R4 `/r4/login/`、R5 `/r5/login/`）。

> 实测踩到的坑：`views.require_login` 首版硬编码 `/r4/login/`，
> 导致 R5 环境下匿名请求跳到 R4 登录页且测试登录失败。已改为读
> `settings.LOGIN_URL`，并在两个 settings 里显式设置。

## 8. 验收证据

```
python manage.py test smass_data_exchange --settings=smass.settings_r5
Ran 85 tests in 36.296s
OK   exit 0
```

（85 = R4 引擎 42 + R4 HTTP 18 + R5 25）

```
python manage.py test smass_data_exchange --settings=smass.settings_r4
Ran 61 tests in 18.861s
OK (skipped=1)   exit 0
```

（61 = 42 + 18 + 1 个跳过的 R5 模块；settings_r4 没有 smass_academic）

### R5 专项 25 例分布

| 类 | 例数 | 覆盖 |
|---|---|---|
| `DatasetRegistrationTests` | 3 | 五数据集注册；模板可生成；**枚举取值来自模型** |
| `AcademicYearImportTests` | 4 | 创建；日期区间非法；文件内重复；二次导入幂等 skip |
| `TermImportTests` | 3 | 未知学年；创建；非法学期枚举 |
| `CourseImportTests` | 2 | 创建（含 Decimal 学分）；非法学分 |
| `SectionImportTests` | 4 | 未知课程；未知学期；创建；负容量 |
| `EnrollmentImportTests` | 7 | 创建；**容量满**；**已选占位**；重复跳过；退课恢复；未知账号；关闭教学班；零容量不限 |
| `PermissionTests` | 1 | 学生无导入权限被拒且不写库 |

## 9. 未完成

| 项 | 状态 |
|---|---|
| 教学班教师分配（`TeachingAssignment`）导入 | `PENDING` |
| 批量退课 / 选课调整导入 | `PENDING`（当前只创建与恢复） |
| 真实人员数据 | `BLOCKED_EXTERNAL_AUTH` |
| CSV 导出性能（S25-PERF） | `PENDING` |
