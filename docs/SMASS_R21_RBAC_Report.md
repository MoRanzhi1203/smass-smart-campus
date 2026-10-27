# SMASS R2.1 RBAC 报告（RBAC Report）

## 1. 权限矩阵（`r21_account/permissions.py`）

| 角色 | view_data | add_data | change_data | delete_data | reset_password | import_data | manage_roles | dangerous_bulk_delete |
|---|---|---|---|---|---|---|---|---|
| system_admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **❌ 无人拥有** |
| college_admin | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| teacher | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| student | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

实现载体：`AccountRole`（记录/审计）→ Django `Group`（`r21_*`）→ `Permission`
（content_type 绑定 `r21_account.Account`），判定走标准 `has_perm`。

## 2. 对象级范围（`r21_account/scoping.py`）

| 角色 | 可见学生范围 |
|---|---|
| system_admin | 全部 |
| college_admin | `StudentProfile.college_name == account.scope_college`；scope 为空 → **拒绝** |
| teacher | 同上（当前原型按学院收敛） |
| student | 仅 `account == 自己` |
| 无角色 / 未登录 / 停用 | **`none()` 默认拒绝** |

> 关键设计：**"scope 为空"不等于"全部"**——避免漏配 scope 时意外放大权限。

## 3. 测试证据（`test_rbac_scope.py`，14 例）

| 类别 | 用例 | 结果 |
|---|---|---|
| 纵向越权 | 学生无任何管理权限（7 项逐一断言） | PASS |
| 纵向越权 | 教师不能 manage_roles | PASS |
| 纵向越权 | 学院管理员不能 delete/reset_password | PASS |
| 纵向越权 | **system_admin 也没有 dangerous_bulk_delete** | PASS |
| 横向越权 | 系统管理员看全部；学院管理员/教师只见本院；学生只见自己 | PASS |
| 横向越权 | 学院管理员 scope 为空 → 0 条 | PASS |
| 横向越权 | `can_access_student` 拒绝他人档案 | PASS |
| 默认拒绝 | 无角色账号 → 0 条 | PASS |
| 停用/匿名 | 停用账号、`None` → 0 条 | PASS |
| 角色撤销 | 撤销后权限消失、可见范围归零 | PASS |
| 伪造入参 | 会话身份不受客户端参数影响 | PASS |

## 4. 高危操作

- 清表类操作：R1.5 已把 HTTP 入口改为 403（`app01` 侧）；
- R2.1 增加独立权限 `dangerous_bulk_delete`，**不授予任何内置角色**（测试锁定）；
- 结论：仅 `confirm=YES` 不构成保护（延续 R1.5 结论）。

## 5. 未做

| 项 | 状态 |
|---|---|
| 把 RBAC 应用到 `app01` 现有后台视图 | **NOT DONE**（正式路径未切换） |
| 学院/班级两级完整 scope（当前按学院） | 部分；班级级待 R2.2 |
| 动态权限编辑 UI | 未做（仅服务层 API） |
