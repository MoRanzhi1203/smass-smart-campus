# SMASS R11 — 排课与课表（求解核心）

状态：**`TESTED`**（模型 + 求解器 + 冲突解释 + 复核，22 例）
裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`
（UI 与发布审批单列为 `R11-UI`，见 §8）

---

## 1. 为什么没有用 CP-SAT

实测本机**没有** OR-Tools / PuLP / MIP / z3 / networkx：

```
ortools: False   pulp: False   mip: False   z3: False   networkx: False
```

安装 OR-Tools 会引入数十 MB 依赖并需要额外审计。主任务书明确允许
"deterministic constructive fallback where necessary"，因此实现
**确定性构造 + 有限回溯**，并且：

- **不声称全局最优**；
- 只声称"硬冲突为 0，或明确报不可行 + 可读原因"；
- 同输入必得同结果（可复现、可审计）。

## 2. 数据模型（`smass_scheduling`）

| 模型 | 表 | 关键字段 / 约束 |
|---|---|---|
| `TimeSlot` | `smass_scheduling_timeslot` | `(weekday,period)` 唯一；`period>=1`；`weekday∈[0,6]` |
| `TeacherProfile` | `smass_scheduling_teacher_profile` | `instructor_type`、`weekly_hour_cap`、`max_daily_periods` |
| `TeacherAvailability` | `smass_scheduling_availability` | `(account,weekday,period)` 唯一；**有记录=仅这些时段可用** |
| `TeacherConstraint` | `smass_scheduling_teacher_constraint` | `kind ∈ {unavailable, prefer, avoid}`；`approved_by` 非空才算"已批准" |
| `Cohort` | `smass_scheduling_cohort` | 修读群体（学生冲突的可实施近似） |
| `ScheduleRun` | `smass_scheduling_run` | 批次状态、算法、硬冲突数、软成本、`explanation`(JSON) |
| `LessonRequirement` | `smass_scheduling_requirement` | `weekly_sessions`、`session_periods`、`students`、`required_room_type`、`priority` |
| `ScheduleEntry` | `smass_scheduling_entry` | 结果；**四个唯一约束**把硬约束下沉到数据库 |
| `ScheduleConflict` | `smass_scheduling_conflict` | 冲突/不可行解释逐条落库 |

`ScheduleEntry` 的四个唯一约束：

```
(run, room, weekday, period)          -- 教室不冲突
(run, teacher, weekday, period)       -- 教师不冲突
(run, cohort, weekday, period)        -- 群体不冲突
(run, requirement, weekday, period)   -- 同一需求同一时段不重复
```

这意味着**即使求解器有 bug，数据库也不会接受同教室/同教师/同群体的双重占用**。

### 职称不授予任何权限

`instructor_type`（教授/副教授/讲师/实验员/行政双肩挑/外聘）**只**影响
`weekly_hour_cap` 的默认值：

```python
DEFAULT_WORKLOAD_CAPS = {
    'professor': 12, 'associate_professor': 14, 'lecturer': 16,
    'lab_teacher': 18, 'admin_dual': 6, 'visiting': 8,
}
```

可由 `settings.SCHEDULING_WORKLOAD_CAPS` 覆盖。职称不产生任何授权效果——
这是主任务书"Job title alone grants no invented privilege"的直接落实。

## 3. 硬约束

| 硬约束 | 实现 |
|---|---|
| 教师同一时段唯一 | `used_teacher` 集合 + DB 唯一约束 |
| 教室同一时段唯一 | `used_room` 集合 + DB 唯一约束 |
| 群体（学生）同一时段唯一 | `used_cohort` 集合 + DB 唯一约束 |
| 教室容量 | `room.capacity == 0` 不限；否则 `students <= capacity` |
| 教室类型 | `required_room_type` 非空时必须匹配 |
| 教师已批准不可用 | 只认 `approved_by` 非空的 `unavailable` 约束 |
| 教师"仅这些时段可用" | 有 `TeacherAvailability` 记录时，不在集合内的时段全部排除 |
| 周课时上限 | `weekly_hour_cap` 或按教师类型的默认值 |
| 单日节数上限 | `max_daily_periods`（0 = 不限） |
| 教室维护封闭期 | 维护期 → 周内时段阻塞集合（保守：覆盖任一天即阻塞） |
| 课时数 | 每个需求的节次必须排满，否则记 `unplaced_requirement` |

### 维护期的处理（诚实说明）

排课结果是**周模板**（每周重复），而 `MaintenanceWindow` 是绝对时间。
判定规则：只要维护区间覆盖了学期内**任意一个**该 `(weekday, period)` 实例，
就把该组合视为不可用。

- 优点：保守、安全，不会把课排进真实维护时间；
- 代价：短期维护会过度限制整个学期该时段；
- 后续改进方向：引入"教学周 → 具体日期"映射，把维护限制到具体周次。

## 4. 软约束与成本

```python
DEFAULT_WEIGHTS = {
    'prefer_hit': -12,        # 命中教师偏好 -> 降低成本
    'avoid_hit': +25,         # 命中教师回避 -> 提高成本
    'same_room_bonus': -8,    # 同一需求尽量同教室
    'gap_penalty': +6,        # 同一天出现空档
    'capacity_waste': +1,     # 每浪费 10 个座位 +1
    'instructor_type_bonus': -2,
}
```

候选排序键：`(score, weekday, period, room.code)`——**包含 room.code**，
保证同分时也有确定顺序（这是"确定性"的实现细节，否则集合遍历顺序会导致不可复现）。

## 5. 不可行时的解释

`ScheduleRun.explanation` 是 JSON 数组，逐条给出：

```json
{"requirement": 7, "section": "CS101-01", "teacher": "T-1001",
 "placed": 0, "needed": 2, "reason": "该教师在所有时段都不可用（可用性/约束过严）"}
```

`_failure_reason()` 的判定顺序：

1. 没有可用教室 → `没有可用教室`
2. 没有满足类型/容量要求的教室 → `没有满足类型/容量要求的教室（需要 N 人）`
3. 教师所有时段不可用 → `该教师在所有时段都不可用（可用性/约束过严）`
4. 教师/群体时段被占满 → `教师或班级的可用时段已被其它课程占满`
5. 教室时段被占/维护 → `合适教室在这些时段全部被占用或处于维护期`
6. 其它 → `剩余的可用时段不足（每周需要 K 次）`

同时写入 `ScheduleConflict` 行，便于在 UI 上逐条展示。

## 6. 独立复核 `verify_run`

与求解器**分开实现**（不自己验证自己），检查：

- 教室/教师/群体重复占用（按 `(id, weekday, period)` 分组计数）
- 容量不足、教室类型不匹配
- 教师已批准不可用
- 教室维护期
- 课时数是否等于 `weekly_sessions × session_periods`

返回问题列表（`kind` + 定位信息），空列表表示复核通过。

## 7. 验收证据

```
python manage.py test smass_scheduling --settings=smass.settings_r11
Ran 22 tests in 16.326s
OK      exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `SolverBasicsTests` | 4 | 全部排入、状态更新、无冲突行、复核通过 |
| `TeacherConflictTests` | 5 | 教师不重复占用、已批准不可用被遵守、**未批准约束被忽略**、可用时段限制、周课时上限 |
| `RoomConflictTests` | 2 | 教室不重复占用、维护期时段不被排课 |
| `CapacityAndTypeTests` | 3 | 容量不足报原因、类型要求被遵守、无匹配类型 → 不可行 |
| `CohortConflictTests` | 1 | 同一群体不重复占用 |
| `SoftCostTests` | 3 | 偏好时段被选中、软成本被记录、容量浪费计入 |
| `DeterminismTests` | 1 | **同输入同输出**（两次求解的签名完全一致） |
| `VerifyRunTests` | 2 | 数据库唯一约束拒绝重复、课时数不符被检出 |
| `ExplanationTests` | 1 | 不可行时给出可读原因并落库 |

### 里程碑回归（13 套件）

```
suite                                    count   result
smass_operations                          0      FAILED (环境残留, 见下)
smass_analytics                           31     OK
smass_organization                        69     OK
S25 roundtrip+ui (r4)                     60     OK
S25 r5 adapter (r5)                       25     OK
smass_academic                            56     OK
smass_facilities                          42     OK
smass_workflow                            41     OK
smass_api                                 23     OK
r22_account                              117     OK
r21_account                              110     OK
app01                                    163     OK
tests_e2e                                 16     OK
```

`smass_operations` 的失败**不是产品缺陷**：上一次回归被我主动终止后，
`test_smass_r10_release` 测试库残留，导致本次 `CREATE DATABASE` 失败
（3.1 秒 0 用例）。清理残留库后单跑：

```
python manage.py test smass_operations --settings=smass.settings_r10
exit 0
```

这类"终止进程 → 测试库残留"是本机操作副作用，已记录在检查点文档里。

## 8. 未完成（诚实标注）

| 项 | 状态 | 说明 |
|---|---|---|
| **R11-UI**（教务规划页、学生/教师/教室课表、发布审批） | `PENDING` | 单列任务 `R11-UI` |
| **局部重排**（partial reschedule） | `PENDING` | 当前只做全量求解；`solve()` 每次删除该 run 的结果重排 |
| **差异对比 / 审批 / 回滚** | `PENDING` | 需 R11-UI |
| **教学周 → 日期映射** | `PENDING` | 维护期目前保守地按周模板阻塞 |
| **选课人数与群体人数的联动** | `PENDING` | 当前 `LessonRequirement.students` 手工给定 |
| **与 Excel 模板集成**（排课需求导入） | `PENDING` | 引擎已具备（S25），适配器待写 |
| 真实教学数据 | `BLOCKED_EXTERNAL_AUTH` | 全部合成 |

> 不把"求解器通过 22 例"说成 R11 完成：任务书要求 R11 有学生/教师/教室课表与
> 教务规划界面，那些在 `R11-UI` 中完成。
