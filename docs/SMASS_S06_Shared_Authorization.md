# SMASS S06 — 共享授权：默认拒绝的五维门面

状态：**`TESTED`**（引擎与验收通过；业务模块的**接入**随 R11–R20 逐版落地，见 §7）
裁决：`DEV_COMPLETE` / `SYNTHETIC_TECHNICAL_GO`

---

## 1. 现状核查

| 既有能力 | 位置 | 结论 |
|---|---|---|
| RBAC（Django Permission + Group） | `r21_account/permissions.py` | 已实现，8 个动作 codename |
| 组织域收窄 | `r21_account/scoping.py` | 仅覆盖 student/teacher 两类档案 |
| 对象级归属判断 | `scoping.can_access_student` | 仅单点，未通用化 |
| 字段级 | — | **缺失** |
| 业务状态 | — | **缺失** |
| 统一门面 | — | **缺失**（各视图各写一套，正是漏洞来源） |

本轮不重写既有 RBAC/scoping，而是**在其上**新增统一门面
`r21_account/authorization.py`，补齐字段级与状态级，并提供
service / view / API / report / export 都能调用的同一套 API。

## 2. 五维授权

### 2.1 RBAC（动作 → permission）

```python
ACTION_PERMISSIONS = {
    'view': 'view_data', 'create': 'add_data', 'update': 'change_data',
    'delete': 'delete_data', 'import': 'import_data', 'export': 'view_data',
    'reset_password': 'reset_password', 'manage_roles': 'manage_roles',
    'bulk_delete': 'dangerous_bulk_delete',
}
```

未知动作 → `has_action` 返回 `False`（默认拒绝）。
`dangerous_bulk_delete` 不授予任何默认角色（沿用既有安全设定）。

### 2.2 组织域（查询集收窄）

`scope_queryset(account, resource, qs=None)` 直接返回**已过滤的 QuerySet**：

- 无角色 / 停用 / 匿名 → `qs.none()`；
- `system_admin` → 全量；
- `college_admin` / `teacher` → 按 `scope_college` 过滤；
- **`scope_college` 为空 → `qs.none()`**（"空"不等于"全部"，这是最容易被写错的默认值）；
- `student` → 仅本人。

### 2.3 对象级（防 IDOR）

```python
require_object(account, resource, obj, action='view')
```

三重检查：对象存在 → 有动作权限 → 对象在可见集合内。任一失败抛
`AuthzDenied`（reason 分别为 `object_missing` / `action_forbidden` /
`object_out_of_scope`），调用方统一转 403。

实现上不是"在 Python 里过滤列表"，而是 `scope_queryset(...).filter(pk=obj.pk).exists()`
——判定口径与列表页完全一致，避免"列表看不到但详情能打开"。

### 2.4 字段级（允许列表 + 脱敏）

```python
FIELD_ALLOW = {('student', RoleCode.TEACHER): {'student_no','name','college_name','classes_name'}, ...}

visible_fields(account, resource)      # frozenset 或 ALL_FIELDS
redact(account, resource, data, obj)   # 未允许的键直接消失
```

- **允许列表而非黑名单**：模型新增字段时默认不可见（fail-closed）；
- 敏感字段（`card_id` / `phone` / `password`）即使可见也走掩码：
  `13900002222` → `139******22`；
- 只有 `system_admin` 拿到未脱敏值；
- `redact()` 返回**新 dict**，未授权键在输出里根本不存在。

### 2.5 业务状态

```python
DEFAULT_TRANSITIONS = {
    'student': {
        'active':    {'suspend': {SYSTEM_ADMIN, COLLEGE_ADMIN}, 'graduate': {SYSTEM_ADMIN}},
        'suspended': {'reinstate': {SYSTEM_ADMIN}},
        'graduated': {},   # 终态
        'withdrawn': {},   # 终态
    },
}
```

- 未知资源 / 未知状态 / 未知动作 → **拒绝**（`UNKNOWN_TRANSITION_ALLOWED = False`）；
- `settings.AUTHORIZATION_TRANSITIONS` 可覆盖/扩展，便于学校政策落地而不改代码；
- 学校具体学籍规则未确认 → 标记 `BUSINESS_CONFIG_PENDING`，保持默认最小规则。

## 3. 默认拒绝的四个入口

| 场景 | 行为 |
|---|---|
| 匿名 / 无角色 | 所有动作 `False`；`scope_queryset` 空集；`redact` 返回 `{}` |
| 停用账号 | 同上（`active_roles` 返回空集） |
| 未知资源 | 抛 `AuthzDenied('unknown_resource')` |
| 未知动作 / 未知状态转换 | 拒绝，不 fallback 到"允许" |

## 4. 认证证据

### 4.1 新增 `r21_account/tests/test_s06_authorization.py` — 38 例

```
python manage.py test r21_account.tests.test_s06_authorization --settings=smass.settings_r21
Ran 38 tests in 9.856s
OK      exit 0
```

| 类 | 例数 | 覆盖 |
|---|---|---|
| `DefaultDenyTests` | 5 | 匿名/无角色/停用/未知动作/未知资源 |
| `RbacMatrixTests` | 4 | 系统管理员不获 bulk_delete；学院管理员无 delete/reset；学生无写；`require_action` 抛错 |
| `ScopeTests` | 4 | 按院收窄；**空 scope 不看任何数据**；系统管理员全量；学生仅本人 |
| `ObjectLevelIdorTests` | 4 | 跨院拒绝（`object_out_of_scope`）；同院允许；教师可读不可改；空对象拒绝 |
| `FieldLevelTests` | 9 | 允许列表；教师看不到 phone/card；学生看不到 card；`redact` 丢键；掩码格式；管理员不掩码；匿名空 dict；无 update 则全字段不可写 |
| `StateMachineTests` | 7 | active→suspend 允许；终态拒绝；未知动作/状态拒绝；学生不能转换；`require_transition` 抛错；settings 可扩展 |
| `DescribeTests` | 3 | 诊断只输出能力不含值；匿名描述；拒绝消息不含敏感值 |

### 4.2 全套件回归

```
python manage.py test r21_account --settings=smass.settings_r21
Found 110 test(s)
Ran 110 tests in 90.939s
OK      exit 0
```

（基线 72 + S06 38 = 110）

## 5. 一个被测试抓到的实现缺陷

首版 `_model()` 用 `importlib.import_module('r21_account')` 再 `getattr(module, 'StudentProfile')`，
在 `r21_account/__init__.py` 未导出模型时抛 `AttributeError`。已改为
`django.apps.apps.get_model(app_label, model_name)`——这是 Django 解析模型的正确方式，
也避免在 app 初始化早期触发导入循环。

同时修正 `AuthzDenied` 的 `__str__`：初版只输出 reason，排查时看不到是哪个字段被拒；
现输出 `reason resource=... action=... detail=<字段名>`，**detail 只放字段名，不放字段值**。

## 6. 与任务书要求的对应

| 要求 | 实现 |
|---|---|
| 默认拒绝 RBAC | `has_action` + 未知动作 False |
| 组织域 | `scope_queryset`（空 scope = 空集） |
| 对象级 | `require_object`（三检） |
| 字段级 | `visible_fields` / `redact` / `check_write_fields` |
| 业务状态 | `can_transition` / `require_transition` |
| 负向 IDOR / 参数伪造测试 | `ObjectLevelIdorTests` + `DefaultDenyTests` |

## 7. 边界与未做的事（诚实标注）

| 项 | 状态 | 说明 |
|---|---|---|
| 门面引擎 | **TESTED** | 本轮完成 |
| UI / API / report / import / export 的**接入** | `INCREMENTAL` | 门面已提供；各业务模块在 R11–R20 实现时统一调用。**不宣称全链路已接入** |
| `StudentProfile.status` 字段 | **不存在** | 状态机为引擎级验证（用 stub 对象）；真实状态字段随 R12 学籍异动落地 |
| 学校具体学籍政策 | `BUSINESS_CONFIG_PENDING` | 通过 `AUTHORIZATION_TRANSITIONS` 可配置，默认最小规则 |
| 字段级与既有 `scoping.py` 合并 | **未合并** | `scoping.py` 保持不动以免破坏既有测试；门面内部复用同一判定口径 |

> 声称"四维授权已在所有层一致生效"是不诚实的：本轮交付的是**唯一门面 + 引擎验收**，
> 接入是逐模块的工作，账本里由 R11–R20 各自承担。

## 8. 安全性声明

- 未修改 `AUTH_USER_MODEL`（实测 `auth.User`）与正式认证配置。
- 拒绝消息与 `describe()` 输出均不含字段值（有测试断言）。
- 正式 `smass` 库 0 写入。
- 未读取真实档案数据；全部测试用合成账号与合成证件/手机号。
