# SMASS R16 — 校园场地与设备资源

状态：**`TESTED`**（模型 / 服务 / 冲突与生命周期；UI 与"设备预约"细分待 R16-UI）
裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`

---

## 1. 数据模型

新增独立 app `smass_facilities`（`smass.settings_r16`，库前缀 `smass_r16_`）。

| 模型 | 表 | 关键字段 |
|---|---|---|
| `Building` | `smass_facilities_building` | `code`(唯一)、`name`、`campus`、`is_active` |
| `Equipment` | `smass_facilities_equipment` | `code`(唯一)、`name`、`kind` |
| `Room` | `smass_facilities_room` | `code`(唯一)、`building`、`room_type`、`capacity`、`seat_count`、`status`、`requires_qualification`、`requires_approval` |
| `RoomEquipment` | `smass_facilities_room_equipment` | `(room,equipment)` 唯一、`quantity` |
| `RoomQualification` | `smass_facilities_qualification` | `(room,account)` 唯一、`expires_at` |
| `RoomAvailability` | `smass_facilities_availability` | `(room,weekday,start,end)` 唯一 |
| `MaintenanceWindow` | `smass_facilities_maintenance` | `room`、`start_at`、`end_at`、`reason` |
| `RoomBooking` | `smass_facilities_booking` | `room`、`account`、`start_at`、`end_at`、`status`、`attendees` |

数据库约束（真实建在表上）：

- `r16_room_capacity_nonneg`、`r16_room_seat_nonneg`
- `r16_booking_time_order`（`end_at > start_at`）
- `r16_booking_attendees_nonneg`
- `r16_uniq_room_equipment`、`r16_uniq_room_qualification`、`r16_uniq_room_availability`

索引：`(room,start_at,end_at)`、`(account,start_at)`、`(status)`、`(building,room_type)`、
`(status,is_active)`、`(room,start_at)`、`(room,weekday)`。

## 2. 业务规则（服务层强制）

`smass_facilities/services.py` 的 `create_booking()` 按顺序校验，任一失败即拒绝且**不写库**：

1. 用途非空；`end > start`；不允许预约过去时间（5 分钟宽限）；
2. 账号有有效角色（预约是普通用户操作，不要求管理权限）；
3. 房间 `is_active` 且 `status == open`；
4. 需要资格的房间：账号有未过期的 `RoomQualification`；
5. 容量：`capacity > 0` 时 `attendees <= capacity`（`capacity == 0` 表示不限）；
6. 区间完整落在某个 `RoomAvailability` 内（**未配置时段 = 全天可用**）；
7. 无 `MaintenanceWindow` 重叠；
8. 无其它占用中预约重叠。

**时间不重叠**的实现：

```python
RoomBooking.objects.filter(
    room=room, status__in=OCCUPYING_STATUSES,
    start_at__lt=end_at, end_at__gt=start_at)   # 标准区间重叠判定
```

因为 MySQL 无法用 CHECK 表达区间互斥，并发安全靠：

```python
with transaction.atomic():
    Room.objects.select_for_update().get(pk=room.pk)   # 锁住房间行
    ... 再查冲突 ...
```

同一房间的并发请求因此**串行化**。

`OCCUPYING_STATUSES = (pending, approved, checked_in)`——待审批也占位，
避免两个申请同时被批准造成双重占用。

## 3. 生命周期状态机

```
create ──(无需审批)──> approved ──签到──> checked_in ──释放──> released
   └──(需要审批)──> pending ──批准──> approved
                      │                 └──逾期未签到──> no_show
                      └──取消──> cancelled
```

| 操作 | 前置状态 | 权限 |
|---|---|---|
| `approve_booking` | `pending` | `update` 权限，且**不能自批**（`SELF_APPROVAL_DENIED`） |
| `cancel_booking` | 非终态 | 本人或有 `update` 权限 |
| `check_in_booking` | `approved` | 本人或有 `update` 权限 |
| `mark_no_show` | `pending`/`approved` | `update` 权限 |
| `release_booking` | `approved`/`checked_in` | 本人或有 `update` 权限 |
| `auto_mark_no_shows` | `approved` 且超宽限期 | 批量任务（默认 15 分钟宽限） |

释放与取消都会写 `released_at`，使该时段**立即可被再次预约**（有测试验证）。

## 4. 授权域

`scoped_bookings(account)`：

| 角色 | 可见范围 |
|---|---|
| `system_admin` | 全部 |
| `college_admin` | 所在校区（`scope_college` 匹配 `building.campus`；空 scope → 空集） |
| `teacher` / `student` | 仅本人 |
| 无角色 / 匿名 | 空集 |

> 诚实标注：`college_admin` 用 `building.campus` 匹配 `scope_college` 是**当前唯一可用的组织维度**；
> 若后续引入"楼宇归属学院"，应改为按楼宇归属过滤。这一点已在此记录，避免被误读为已完成。

## 5. 查询能力

| 函数 | 用途 |
|---|---|
| `find_conflicts(room, start, end, exclude_id=)` | 冲突预约 |
| `find_maintenance(room, start, end)` | 封闭期重叠 |
| `availability_windows(room)` / `is_within_availability(...)` | 常规可用时段 |
| `has_qualification(account, room, at=)` | 资格（含过期判断） |
| `room_calendar(room, start, end)` | **共享日历**：占用 + 封闭期 + 可用时段 |
| `available_rooms(start, end, room_type=, min_capacity=)` | 该时段可预约房间（排除占用与维护） |

## 6. 验收证据

```
python manage.py test smass_facilities --settings=smass.settings_r16
Ran 42 tests in 36.173s
OK      exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `RoomModelTests` | 3 | `bookable` 反映状态；设备数量；容量约束存在 |
| `BookingConflictTests` | 8 | 正常创建、**重叠拒绝**、相邻允许、异房不影响、取消/释放后释放时段、区间非法、过去时间 |
| `RoomStatusAndMaintenanceTests` | 3 | 停用房拒绝、**封闭期拒绝且不写库**、封闭期相邻允许 |
| `QualificationTests` | 4 | 实验室无资格拒绝、有资格通过、**过期资格拒绝**、普通教室无需资格 |
| `CapacityAndAvailabilityTests` | 4 | 超容量拒绝、容量 0 不限、**时段外拒绝**、未配时段=全天 |
| `ApprovalFlowTests` | 5 | 需审批进 pending、批准生效、**自批拒绝**、教师不能批、pending 占位 |
| `LifecycleTests` | 5 | 签到、未批准不能签到、管理员标爽约、无权限不能标、批量爽约、他人不能取消 |
| `CalendarAndSearchTests` | 4 | 日历列出占用、可用房间排除占用/维护、按类型与容量过滤 |
| `ScopedBookingTests` | 4 | 教师只见自己、管理员见全部、匿名空集、无角色空集 |
| `ConcurrencyTests` | 1 | **并发双预约不产生两条重叠记录** |

审计日志实测输出：

```
INFO smass.audit: room_booking_created id=19 room=26 account=25 status=approved
INFO smass.audit: room_booking_created id=24 room=33 account=35 status=pending
INFO smass.audit: room_booking_checked_in id=23
INFO smass.audit: room_booking_no_show id=25 by=38
INFO smass.audit: room_booking_no_show_batch count=1
```

## 7. 与 R11 的关系

R11 排课需要的"教室资源"要素已具备：

| R11 需要 | R16 提供 |
|---|---|
| 房间与容量 | `Room.capacity` / `seat_count` |
| 教室类型适配 | `Room.room_type` |
| 设备要求 | `RoomEquipment` |
| 可用时段 | `RoomAvailability` + `is_within_availability` |
| 维护封闭期 | `MaintenanceWindow` + `find_maintenance` |
| 与既有预约不冲突 | `find_conflicts` |

R11 将在排课时以"已存在的 R16 预约"为硬约束之一。

## 8. 未完成（诚实标注）

| 项 | 状态 | 说明 |
|---|---|---|
| **R16 UI**（房间列表 / 日历 / 预约表单 / 审批页） | `PENDING` | 本轮只交付模型与服务层 + 42 例测试；页面在 R16-UI 任务中完成 |
| 设备级预约（借投影仪等） | `PENDING` | 当前设备只作为房间属性 |
| 座位级预约（`seat_count` 细分到具体座位） | `PENDING` | 当前按房间整体预约 |
| 周期性预约（每周重复） | `PENDING` | 当前一次一条 |
| 真实场地数据 | `BLOCKED_EXTERNAL_AUTH` | 全部使用合成楼宇/房间 |
| 与 R11 排课的联动写入 | `PENDING` | 属 R11 范围 |

> 不把"服务层完成 + 无 UI"说成 R16 全部完成：任务书要求每个版本有真实页面，
> 因此 R16 的 UI 被单列为后续任务，账本里不合并。
