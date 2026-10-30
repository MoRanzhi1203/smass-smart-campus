# SMASS R11-UI — 排课规划与三张课表

状态：**`TESTED`** · 18 例 HTTP 层测试
配套：`docs/SMASS_R11_Scheduling.md`（模型与求解器）

---

## 1. 路由

`smass/urls_r11.py`（`settings_r11.ROOT_URLCONF`）

| 方法 | 路径 | 作用 | 权限 |
|---|---|---|---|
| GET | `/r11/plan/` | 教务规划页（批次列表 + 求解说明 + 已排课次） | 管理员（`system_admin` / `college_admin`） |
| POST | `/r11/plan/<id>/solve/` | 运行求解 | `create` 动作 |
| POST | `/r11/plan/<id>/publish/` | 发布批次 | `update` 动作 + 复核通过 |
| GET | `/r11/plan/<id>/conflicts/` | 冲突明细（JSON） | 管理员 |
| GET | `/r11/timetable/student/` | 学生课表 | 登录 + 按 `Enrollment` 收窄 |
| GET | `/r11/timetable/teacher/` | 教师课表 | 登录 + 按本人收窄 |
| GET | `/r11/timetable/room/<pk>/` | 教室课表 | 管理员 |
| GET | `/r11/timetable/mine.json` | 我的课表 JSON | 登录 |

## 2. 关键行为

### 2.1 只有 `published` 批次对课表可见

`_published_runs()` 只取 `status == published` 的批次；学生/教师在发布前看到的是
"还没有已发布的排课批次"，不会看到未审批的草稿结果。

### 2.2 发布门槛（三道）

```
POST /publish/
  ├─ 状态必须是 solved                    -> 否则 400
  ├─ run.hard_conflicts 必须为 0          -> 否则 400
  └─ solver.verify_run(run) 必须为空      -> 否则 400 + problems 列表
```

第三道是**独立复核**（与求解器分开实现），避免把"求解器自己认为没问题"的结果发出去。

### 2.3 学生课表的收窄方式

```python
sections = Enrollment.objects.filter(account=user).exclude(status='dropped')
entries = ScheduleEntry.objects.filter(run=run,
                                       requirement__section_id__in=sections)
```

即"我选过课的教学班所对应的排课"。退课（`dropped`）不显示。

### 2.4 教师课表

`ScheduleEntry.objects.filter(run=run, teacher=user)`——只看本人。
测试验证"另一个教师看到的是空课表"，不是看到别人的课。

### 2.5 教室课表

仅管理员可访问（非管理员 403）。展示该教室在某批次下的全部占用。

### 2.6 课表矩阵渲染

`_grid(entries, periods, days)` 生成 `grid[weekday][period]`，
模板按 7 天 × N 节渲染；同一格多门课会**堆叠显示**（正常情况下不应发生，
因为数据库唯一约束禁止同群体/同教室/同教师同时段重复）。

## 3. 验收证据

```
python manage.py test smass_scheduling --settings=smass.settings_r11
Ran 40 tests in 57.250s
OK      exit 0
```

（22 求解器 + 18 UI）

| 类 | 例数 | 覆盖 |
|---|---|---|
| `PlanPageTests` | 4 | 匿名跳登录、学生 403、管理员 200、教师 403 |
| `SolveAndPublishTests` | 7 | 求解返回结果、无权限 403、未求解不能发布、发布成功、**复核失败拒绝发布**、冲突接口、已发布不能重解 |
| `TimetableVisibilityTests` | 7 | 发布前空、发布后学生可见课程与教学班、教师可见、**其他教师看不到**、教室课表限管理员、我的课表 JSON 字段、匿名跳转 |

### 实测日志片段

```
WARNING django.request: Forbidden: /r11/plan/            # 学生/教师进规划页
WARNING django.request: Bad Request: /r11/plan/7/publish/ # 未求解就发布
WARNING django.request: Bad Request: /r11/plan/9/publish/ # 复核失败
WARNING django.request: Bad Request: /r11/plan/10/solve/  # 已发布不能重解
WARNING django.request: Forbidden: /r11/plan/12/solve/    # 教师求解
WARNING django.request: Forbidden: /r11/timetable/room/15/ # 教师看教室课表
```

## 4. 一个被测试抓到的配置缺陷

`settings_r11.LOGIN_URL` 初版写成 `/r21/login/`，而 `urls_r11` 提供的是
`/r11/login/`。后果：匿名访问 `/r11/plan/` 会被引导到 R21 登录页，
登录后 `next` 回跳仍失败。已改为 `/r11/login/`，并对应 R4/R5 也各自设置。

> 教训：只要一个 settings 有自己的 `urls_*`，就必须同时设置 `LOGIN_URL`，
> 否则会串到别的模块的登录页。

## 5. 未完成

| 项 | 状态 |
|---|---|
| 局部重排（只重排某几个需求） | `PENDING` |
| 排课结果差异对比 / 审批流 / 回滚 | `PENDING` |
| 课表导出（Excel/PDF） | `PENDING`（S25 引擎已可复用） |
| 移动端专用布局 | `PENDING`（当前页面为响应式表格） |
| 教师特殊约束的申请与审批界面 | `PENDING`（模型已具备 `approved_by`） |
