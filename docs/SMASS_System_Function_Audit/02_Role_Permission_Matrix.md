# 02 角色权限矩阵

> 依据：`r21_account/permissions.py`（RBAC 矩阵）、`r21_account/authorization.py`
> （五维门面）、`smass_workspace/permissions.py`（产品守卫）、
> 各模块 `services.py` 的角色判定、`smass_workspace/navigation.py`（菜单）。
> 图例：**V** 查看 · **C** 新增 · **U** 编辑 · **D** 删除 · **A** 审批/发布 ·
> **I** 导入 · **E** 导出 · **—** 无权限 · **R** 只读（可查看不可写）。

---

## 1. 三个层面的权限必须分开看

| 层面 | 实现 | 被谁执行 | 失败表现 |
|---|---|---|---|
| ① 菜单可见性 | `navigation.sections_for(kind, account)` | 模板渲染 | 菜单项不出现（**不是安全边界**） |
| ② 页面访问 | `@require_kind` / `@require_system_admin` | 视图守卫 | HTTP 403 + 403 页面 |
| ③ 后端业务权限 | 服务层角色判定 + 对象范围 + 状态机 | 服务函数 | 抛 `*Error` / `PermissionDenied`，页面临时提示或 403 |
| ④ 数据范围 | `scoped_student_records` / `scope_queryset` | 服务与视图 | 空集或 403 |
| ⑤ 字段权限 | `StudentFieldDefinition` + `authorization.redact` | 序列化/模板 | 字段不出现或掩码 |
| ⑥ RBAC codename | `AccountRole` → Group → Permission | `has_action` | 未知动作拒绝 |

> **重要**：RBAC 矩阵（⑥）与业务服务（③）**并存但不完全一致**：
> 服务层多数用"角色集合 + 对象范围"判定（如 `can_manage` 看
> `teacher/college_admin/system_admin`），并不逐次检查 `change_data` codename。
> 因此不能仅凭 RBAC 矩阵推断业务能力，也不能仅凭菜单推断后端权限。

---

## 2. RBAC 动作矩阵（实际定义）

`ACTION_PERMISSIONS`（9 个动作）与 `ROLE_PERMISSIONS`（4 个角色）：

| 动作（codename） | system_admin | college_admin | teacher | student |
|---|---|---|---|---|
| `view_data`（view/export） | ✅ | ✅ | ✅ | — |
| `add_data`（create） | ✅ | ✅ | — | — |
| `change_data`（update） | ✅ | ✅ | — | — |
| `delete_data`（delete） | ✅ | — | — | — |
| `reset_password` | ✅ | — | — | — |
| `import_data` | ✅ | ✅ | — | — |
| `manage_roles` | ✅ | — | — | — |
| `dangerous_bulk_delete` | —（**任何角色都不授予**） | — | — | — |
| `export`（映射到 `view_data`） | ✅ | ✅ | ✅ | — |

**实际授予计数**：7 + 4 + 1 + 0 = **12 个角色-动作授予**；
`dangerous_bulk_delete` 显式不授予任何角色（`permissions.py` 注释与矩阵一致）。

> 注意：学院管理员在 RBAC 层有 `add/change/import`，但产品端对
> "建课/建班/建场地/发活动/发公告/改学籍"使用 `require_system_admin` 收紧。
> 两者不冲突，但**说明 RBAC 不是产品写权限的唯一来源**。

---

## 3. 菜单可见性矩阵（三端 × 模块）

学生端菜单 14 项（不含管理员端），教师端 10 项（辅导员 +3），管理端 20 项。

| 业务模块 | 学生 | 教师 | 辅导员 | 学院管理员 | 系统管理员 |
|---|---|---|---|---|---|
| 学习工作台 / 课表 / 课程 / 学籍 | 可见 | — | — | — | —（无学生角色时） |
| 考勤与请假 | 可见 | 可见（考勤管理/登记） | 可见 + 请假审批 | 管理端审批 | 管理端审批 |
| 费用与账单 | 可见 | — | — | — | — |
| 场地预约 | 可见 | 可见（审批中心内） | 可见（审批中心内） | 管理端预约审批 | 管理端预约审批 |
| 活动与志愿 | 可见 | — | — | 管理端活动管理 | 管理端活动管理 |
| 社团 / 学生组织 | 可见 | — | — | 管理端社团页 | 管理端社团页 |
| 寝室 | 可见 | — | — | — | — |
| 通知公告 / 通知中心 / 个人中心 | 可见 | 可见 | 可见 | 可见 | 可见 |
| 教学工作台 / 我的课程 / 教学班 / 课表 | — | 可见 | 可见 | — | — |
| 学生事务 / 学生档案 / 审批中心 | — | 可见 | 可见 | — | — |
| 负责班级 / 负责学生 / 请假审批 | — | **不可见** | 可见 | — | — |
| 管理控制台（22 页） | — | — | — | 可见（除系统配置） | 全部可见 |
| 系统配置与权限治理 | — | — | — | **不可见** | 可见 |

> 菜单隐藏不等于拒绝：§4 给出同一批 URL 的直接访问结果。

---

## 4. 页面访问矩阵（直接访问 URL）

实测来源：`smass_workspace/tests/test_workspace.py`（40 例）与
`scripts/product_smoke.py`。

| URL | 匿名 | 学生 | 教师 | 辅导员 | 学院管理员 | 系统管理员 |
|---|---|---|---|---|---|---|
| `/student/` | 302→登录 | 200 | **403** | **403** | **403** | **403**（无学生角色） |
| `/teacher/` | 302→登录 | **403** | 200 | 200 | **403** | **403**（无教师角色） |
| `/teacher/classes/` | 302 | 403 | **403** | 200 | 403 | 403 |
| `/admin/` | 302 | **403** | **403** | **403** | 200 | 200 |
| `/admin/users/` | 302 | 403 | 403 | 403 | 200（只读） | 200（可写） |
| `/admin/settings/` | 302 | 403 | 403 | 403 | **403** | 200 |
| `/admin/records/<外院学号>/` | 302 | 403 | 403 | 403 | **403** | 200 |
| `/teacher/students/<非本班>/` | 302 | 403 | **403** | **403**（非负责班级） | 403 | 403 |
| `/profile/`、`/notifications/` | 302 | 200 | 200 | 200 | 200 | 200 |
| `/no-role/` | 302 | — | — | — | — | —（无角色账号 403） |

**结论**：所有被抽查的越权访问都是**后端 403**，不是仅隐藏菜单。

---

## 5. 后端业务权限矩阵（按模块 × 操作）

标记：✅ 允许 · R 只读 · ❌ 拒绝 · ⚠️ 条件允许（见备注）。

| 模块 | 操作 | 学生 | 教师 | 辅导员 | 学院管理员 | 系统管理员 |
|---|---|---|---|---|---|---|
| 学籍 | 查看本人/范围内 | V（本人） | V（教学班） | V（负责班级） | V（本院） | V（全局） |
| 学籍 | 新建/编辑/删除 | ❌ | ❌ | ❌ | ❌（产品） | ✅（编辑；无删除入口） |
| 学籍 | 导入 | ❌ | ❌ | ❌ | ⚠️（RBAC 有 import，产品无入口） | ✅（导入向导） |
| 学籍 | 导出 | ❌ | ❌ | ❌ | ⚠️（深层页） | ✅（深层页） |
| 教务 | 建学年/学期/课程/教学班 | ❌ | ❌ | ❌ | ❌（产品） | ✅ |
| 教务 | 查看课程/教学班 | V | V（本人） | V | V | V |
| 选课 | 查看名单 | ❌ | V（本人教学班） | V（负责） | V | V |
| 排课 | 查看运行/冲突 | ❌ | ❌ | ❌ | V | V |
| 排课 | 求解/发布 | ❌ | ❌ | ❌ | ⚠️（专业工具 `/r11/plan/`，服务层需管理员） | ✅ |
| 课表 | 学生/教师/教室课表 | V（本人） | V（本人） | V（本人） | V（教室） | V |
| 考勤 | 发起/登记/结束 | ❌ | ✅ | ✅ | ❌（无入口） | ⚠️（深层） |
| 考勤 | 学生签到 | ✅（本人） | — | — | — | — |
| 请假 | 提交/撤销 | ✅（本人） | ❌ | ❌ | ❌ | ❌ |
| 请假 | 审批/驳回 | ❌ | ✅（范围内） | ✅（负责） | ✅（本院） | ✅ |
| 补签 | 提交 | ✅（本人） | — | — | — | — |
| 补签 | 审批 | ❌ | ✅ | ✅ | ⚠️（管理端未列补签） | ⚠️ |
| 场地 | 查看/预约 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 场地 | 取消本人预约 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 场地 | 审批 | ❌ | ⚠️（`can_approve`） | ⚠️ | ✅ | ✅ |
| 场地 | 建档/编辑场地 | ❌ | ❌ | ❌ | ❌（产品） | ✅ |
| 活动 | 报名/取消 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 活动 | 创建/发布/结束/生成学分 | ❌ | ⚠️（深层，`can_manage`） | ⚠️ | ❌（产品） | ✅ |
| 社团 | 申请加入 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 社团 | 审批入社/任命 | ❌ | ⚠️（负责人，深层） | ⚠️ | ⚠️（深层） | ⚠️（深层） |
| 公告 | 查看 | ✅（student/all） | ✅（teacher/all） | ✅ | ✅ | ✅ |
| 公告 | 创建/发布 | ❌ | ❌ | ❌ | ❌（产品） | ✅ |
| 账单 | 查看本人 | ✅ | ❌ | ❌ | ⚠️（深层） | ⚠️（深层） |
| 账单 | 缴费登记 | ✅（本人） | ❌ | ❌ | ⚠️（财务，深层） | ⚠️ |
| 退费 | 申请/审批 | ⚠️（深层） | ❌ | ❌ | ⚠️（深层） | ⚠️ |
| 流程 | 发起/查看 | ⚠️（无产品入口） | ⚠️ | ⚠️ | ⚠️（深层） | ⚠️ |
| 流程 | 完成待办 | ❌ | ✅（本人 assignee） | ✅ | ✅（管理端） | ✅ |
| 组织 | 查看 | V（本人归属） | V | V | V（本院） | V |
| 组织 | 建/改/移动 | ❌ | ❌ | ❌ | ❌（深层 R4 需 `add/change`） | ✅（深层） |
| 用户 | 查看 | ❌ | ❌ | ❌ | V（本院） | V（全局） |
| 用户 | 创建/授角色/停用/重置 | ❌ | ❌ | ❌ | ❌（403） | ✅ |
| 数据导入 | 执行 | ❌ | ❌ | ❌ | ⚠️（RBAC 有 import，产品向导需管理员） | ✅ |
| 数据导出 | 执行 | ❌ | ❌ | ❌ | ⚠️（深层） | ✅ |
| 统计报表 | 查看 | ❌ | ❌ | ❌ | ⚠️（深层 R7） | ⚠️ |
| 监控/审计 | 查看 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 系统配置 | 查看/修改 | ❌ | ❌ | ❌ | ❌（403） | ✅（查看；修改需环境变量重启） |

### 5.1 关键备注

1. **教师 RBAC 只有 `view_data`**，但其能发起考勤、审批请假，是因为
   服务层 `can_manage` 用角色判定（`teacher/college_admin/system_admin`），
   不检查 `change_data`。这是"RBAC 与业务判定并存"的直接体现。
2. **学院管理员 RBAC 有 `add/change/import`**，但产品端建课/建场地/发公告
   使用 `require_system_admin` 收紧；深层 R4/R5 页面则可能按 RBAC 放行。
   同一角色在不同入口的能力不完全一致（见 08 的 P2）。
3. **删除**：产品端没有删除入口；`delete_data` 仅系统管理员持有，
   深层后台（R4/R5 等）可能有删除/批量删除操作。
4. **`dangerous_bulk_delete` 不授予任何角色**，即使系统管理员也没有该 codename。

---

## 6. 数据访问范围矩阵

| 角色 | 学籍 | 用户 | 教学班 | 考勤/请假 | 场地预约 | 账单 |
|---|---|---|---|---|---|---|
| 学生 | 本人 | 本人 | 本人选课 | 本人 | 本人 | 本人 |
| 教师 | 本人教学班学生 | 本人 | 本人任课 | 本人教学班学生 | 本人 | — |
| 辅导员 | 负责班级学生 | 本人 | 本人任课（若有） | 负责班级学生 | 本人 | — |
| 学院管理员 | `scope_college` 子树 | 本院（profile 学院匹配） | 全部（读） | 本院学生 | 全部（审批） | 深层 |
| 系统管理员 | 全部 | 全部 | 全部 | 全部 | 全部 | 全部 |

**范围实现**：

```python
# smass_workspace/permissions.py
def scoped_student_records(account):
    if is_system_admin: return StudentRecord.objects.all()
    if is_college_admin: return filter(unit_id__in=college_unit_ids(account))
    if is_counselor: return counselor_students(account)
    # teacher
    section_ids = TeachingAssignment(account, revoked_at=None)
    account_ids = Enrollment(section in section_ids)
    return StudentRecord(account_id in account_ids)
```

**特殊授权**：`smass_party.AccessGrant`（党建文档分级访问）、
`smass_facilities.RoomQualification`（场地资格）不属于角色矩阵，
是对象级附加授权。

**脱敏**：`authorization.redact` 对手机号/身份证掩码；
`StudentFieldDefinition.is_sensitive` 标记字段；系统管理员可取原值。

---

## 7. 字段级权限

| 字段 | 策略 | 证据 |
|---|---|---|
| `StudentProfile.card_id`（身份证） | 敏感；默认掩码；系统管理员原值 | `StudentFieldDefinition`/`redact` |
| `StudentProfile.phone` | 敏感；掩码（前 3 后 4） | 同上 |
| `Account.password` | 哈希，不进任何页面/日志 | 模型 + 日志约定 |
| `StudentRecord.extra` | 按字段定义过滤（`visible_fields`） | `organization.services.filtered_extra` |
| 党建文档 | `classification` + `AccessGrant.level` | `smass_party.services` |
| API Token | 仅存哈希，签发时显示一次 | `smass_api_security` |

---

## 8. 审批、发布、导入导出权限

| 能力 | 学生 | 教师 | 辅导员 | 学院管理员 | 系统管理员 |
|---|---|---|---|---|---|
| 请假审批 | — | ✅ 范围内 | ✅ 负责 | ✅ 本院 | ✅ |
| 补签审批 | — | ✅ | ✅ | ⚠️ 无产品入口 | ⚠️ |
| 场地审批 | — | ⚠️ `can_approve` | ⚠️ | ✅ | ✅ |
| 学籍异动审批 | — | — | — | ✅ 本院 | ✅ |
| 活动发布/结束 | — | ⚠️ 深层 | ⚠️ | — | ✅ |
| 公告发布 | — | — | — | — | ✅ |
| 角色授予 | — | — | — | — | ✅ |
| 导入执行 | — | — | — | ⚠️ RBAC | ✅ |
| 导出 | — | — | — | ⚠️ 深层 | ✅ |

---

## 9. 超级管理员特权（与普通管理员的差异）

| 能力 | 系统管理员 | 学院管理员 |
|---|---|---|
| 数据范围 | 全局 | 本院子树 |
| 系统配置/权限治理 | ✅ | ❌ 403 |
| 用户/角色写操作 | ✅ | ❌ 403 |
| 建课/建班/建场地/发活动/发公告 | ✅ | ❌ 403 |
| 学籍编辑 | ✅ | ❌（只读） |
| 敏感字段原值 | ✅ | 掩码 |
| 删除类动作 | `delete_data`（无 `bulk_delete`） | ❌ |

**没有"超级管理员绕过业务状态机"的入口**：审批仍经服务层状态校验；
`is_superuser` 只影响 `is_system_admin` 判定与 Django 后台。

---

## 10. 多角色组合与权限冲突

| 组合 | 结果 | 冲突/风险 |
|---|---|---|
| student + teacher | 落地教师端；两端都可访问 | 无 |
| teacher + counselor | 辅导员菜单出现 | **对象范围只按辅导员**，兼课教学班学生详情可能 403（P1） |
| student + college_admin | 落地管理端；学生端仍可访问 | 无 |
| college_admin + system_admin | 系统管理员优先（全局） | 无 |
| 同一账号多个 teacher 角色记录 | `active_roles` 去重 | 无 |
| 角色撤销但会话未过期 | `session_epoch` 递增使旧会话失效 | 已实现 |

---

## 11. 敏感操作的安全机制接入状态

> 结论先行：**独立安全模块存在并通过各自测试，但 `settings_product`
> 未注册这些 App、`urls_product` 未 include 其路由，因此产品三端
> 实际不受 MFA/二次认证/双人审批保护。**

| 机制 | 独立实现 | 产品是否接入 | 证据 |
|---|---|---|---|
| MFA（TOTP + 恢复码） | `smass_mfa`（24 例） | ❌ 未注册 | `settings_product.INSTALLED_APPS` 无 `smass_mfa` |
| 敏感操作二次认证 | `smass_stepup`（26 例） | ❌ 未注册 | 同上 |
| 双人审批 | `smass_stepup`（双人审批 + 执行日志） | ❌ 未注册 | 同上 |
| 字段级策略引擎 | `smass_policy`（25 例） | ❌ 未注册（产品用 `StudentFieldDefinition`） | 同上 |
| 隐私最小化/保留 | `smass_privacy`（25 例） | ❌ 未注册 | 同上 |
| 追加式审计/告警 | `smass_audit`（20 例） | ❌ 未注册（产品用 `AccountAuditLog`/`RequestMetric`） | 同上 |
| 上传安全 | `smass_uploads`（27 例） | ❌ 未注册 | 同上 |
| API scope/幂等/限流 | `smass_api_security`（28 例） | ⚠️ `smass_api` 注册，但安全层未验证 | `settings_product` 无 `smass_api_security` |
| 职责分离（禁自批） | `smass_facilities`（`SELF_APPROVAL_DENIED`） | ✅ 在业务服务内 | `services.approve_booking` |
| 审计日志 | `AccountAuditLog`/`LoginAttempt` | ✅ | 管理端安全审计页 |

**写审计**：账号/角色/考勤/活动/场地/财务等写操作多数调用 `services.audit`
或写状态字段；但**不是所有**服务都写 `AccountAuditLog`（如排课、部分导入）。

---

## 12. 可枚举的权限规则（用于覆盖率核对）

| 类别 | 数量 | 明细 |
|---|---|---|
| RBAC 动作 | 9 | view/create/update/delete/import/export/reset_password/manage_roles/bulk_delete |
| RBAC 角色-动作授予 | 12 | 7+4+1+0 |
| 产品视图守卫 | 4 | `require_kind(student/teacher/admin)`、`require_system_admin` |
| 对象范围规则 | 5 | 学生/教师/辅导员/学院/系统 |
| 字段敏感规则 | 3 | 身份证、手机、密码 |
| 菜单可见规则 | 42 项导航 × 角色过滤 | `navigation.sections_for` |
| 审批权限规则 | 5 | 请假、补签、场地、异动、流程待办 |
| 发布权限规则 | 2 | 公告、活动 |
| 数据范围规则 | 5 | 同上对象范围 |

> 详细逐条证据见 `inventory/urls.csv`、`inventory/views.json`（装饰器）、
> 以及各模块 `services.py` 的 `_require_*`/`can_*` 函数。
