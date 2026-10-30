# R16-UI 场地预约用户界面（验收报告）

- 实现：`smass_facilities/views.py`、`smass_facilities/urls.py`、`smass/urls_r16.py`
- 模板：`templates/r16/`（房间列表、房间详情、共享日历、我的预约、审批、403）
- 服务层：`smass_facilities/services.py`（本轮新增 `reject_booking`）
- 测试：`smass_facilities/tests/test_r16_ui.py`（15 例）、`test_r16_browser.py`（2 例）

## 1. 页面与业务流程

| 路径 | 功能 |
|---|---|
| `/r16/rooms/` | 房间列表；按楼宇/类型/最小容量/空闲时段筛选 |
| `/r16/rooms/<pk>/` | 房间详情、当日占用/维护/可用时段、预约表单 |
| `/r16/calendar/` | 共享日历：按日期查看所有房间占用与维护封闭 |
| `/r16/bookings/` | 我的预约（按角色收窄）、取消/签到/释放 |
| `/r16/approvals/` | 待审批列表、批准/驳回（驳回必须填原因） |

## 2. 权限与负向行为

| 场景 | 结果 |
|---|---|
| 未登录访问任意页面 | 302 到 `/r21/login/?next=…` |
| 学生访问审批页 | 403 |
| 学生预约需资格房间但无资格 | 表单页显示"缺少该房间的使用资格" |
| 容量超限 | 400 页面显示"超过房间容量" |
| 时间冲突 | 400 页面显示"已被占用" |
| 管理员审批自己的预约 | 重定向并显示"不能审批自己提交的预约"，状态保持 `pending` |
| 驳回不填原因 | 重定向并显示"驳回必须填写原因" |
| 取消他人预约 | 重定向并显示"无权取消他人的预约" |
| 审批页对本人提交的行 | 不显示批准/驳回按钮，改为职责分离提示 |

## 3. 数据与状态

- 新增 `BOOKING_REJECTED='rejected'` 状态与迁移
  `smass_facilities/migrations/0002_alter_roombooking_status.py`；
- 驳回写入 `cancel_reason` 与 `released_at`，不再占用房间；
- 所有写操作经 `services`，视图不直接改状态。

## 4. 实测结果

### 4.1 服务端流程（Django Client）

```bash
python manage.py test smass_facilities.tests.test_r16_ui --settings=smass.settings_r16
```

结果：`Ran 15 tests ... OK`，覆盖列表筛选、详情日历、预约、自动批准、
冲突、容量、审批、自批拒绝、驳回原因、签到、释放、越权取消、日历可见性、
预约列表按账号收窄。

### 4.2 真实浏览器流程（Playwright + Chromium）

```bash
python manage.py test smass_facilities.tests.test_r16_browser --settings=smass.settings_r16
```

结果：`Ran 2 tests ... OK`：

1. 学生登录 → 房间列表 → 选择房间 → 填表提交 → 页面显示"预约已提交"；
2. 管理员（独立浏览器上下文）登录 → 审批页 → 批准 → 页面显示"已批准"；
3. 学生刷新"我的预约" → 签到（"签到成功"）→ 释放（"已释放房间"）；
4. 同一房间同一时段再次预约 → 页面显示"已被占用"。

## 5. 已知限制

- 审批列表一次加载全部待审批项；数据量大时需分页（未实现）。
- 共享日历按天展示列表，不是图形化周视图（可后续增强，不影响业务正确性）。
- 定位/签到地理位置未启用：R16 不依赖定位作为占用证据。
