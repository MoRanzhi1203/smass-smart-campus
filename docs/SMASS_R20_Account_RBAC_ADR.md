# SMASS R2.0 统一账号与 RBAC 架构决策记录（ADR）

- 状态：**已形成建议，未做正式切换**
- 决策依据：隔离库原型实测（见 `docs/SMASS_R20_Prototype_Report.md`）
- 明确边界：**正式 `AUTH_USER_MODEL` 切换 = NOT DONE**

## 1. 背景与约束

| 现状 | 约束 |
|---|---|
| `Admin` / `Student` / `Teacher` 三张独立表，各有 `password` | 一轮迁移内不能破坏现有登录与 URL |
| 已应用 `app01` 迁移 0001–0004，`auth`/`admin`/`contenttypes` 迁移已落地 | 中途更换 `AUTH_USER_MODEL` 官方不推荐、不可逆 |
| 无细粒度权限，任一管理员可做任何操作 | R1.5 已把"清表"收口，但 RBAC 仍需设计 |
| 开发库有 6 个账号（1 管理员 / 2 教师 / 3 学生） | 必须能无损迁移且可回滚 |

## 2. 候选路径

### 路径 A：独立业务 `Account` + 自定义认证 Backend

- 新建 `Account`（唯一认证主体）+ `AccountRole` + `StudentProfile`/`TeacherProfile`；
- 认证走自定义 backend（或直接调用 `services/accounts.authenticate` 的扩展版）；
- 旧三表**保留**，通过 `legacy_source`/`legacy_pk` 建立映射；
- 权限复用 Django `Group`/`Permission`。

### 路径 B：自定义 `AUTH_USER_MODEL`（`AbstractBaseUser` + `PermissionsMixin`）

- 把 `Student`/`Teacher`/`Admin` 合并成一个 User 模型，用 `person_type` 区分；
- 设置 `AUTH_USER_MODEL = 'app01.User'`（或新 app）；
- 需要重写 `auth` 相关迁移引用，并处理已存在的 `django_admin_log`、`auth_user_*` 外键。

## 3. 对比

| 维度 | A：独立 Account + Backend | B：自定义 AUTH_USER_MODEL |
|---|---|---|
| 迁移风险 | **低**：只加表，不动既有表 | **高**：`AUTH_USER_MODEL` 变更后官方不支持简单回退；需 `--fake` 或重建 |
| 回滚 | **容易**：停用新表/切回旧路径即可，旧表未改 | **困难**：涉及 `auth`/`admin` 迁移依赖，回退需手工重建 |
| Django 集成成本 | 中：需自定义 backend、`request.user` 适配、Session 中记录激活角色 | 低到中：`request.user` 天然可用，`login()`/`logout()` 直接复用 |
| 与 `Group`/`Permission` 配合 | 需 `Account` 挂 `PermissionsMixin` 或桥接 | 天然支持 |
| 长期维护 | 两套模型并存一段时间，需清理计划 | 单一模型，长期更干净 |
| 对现有 URL/Session 的影响 | **零**（可保留现有登录视图） | 需同步改登录视图、Session 内容、模板 |
| 本轮可行证据 | **已实测**：6 账号回填、密码原样、失败注入 9/9 | 未实测（只评估） |

## 4. 决策

**推荐路径 A**，并把它拆成三步渐进迁移（本轮只完成第 1 步的隔离原型）。

理由（按权重排序）：

1. **可回滚性优先**：本项目是仍在演进的校园系统，B 的不可逆性风险过高；
   计划本身也要求"安全回滚"作为目标之一。
2. **已有实测证据**：A 路径已在隔离库完成 6 个账号的无损回填与 9 项失败注入，
   B 路径**没有任何运行证据**。
3. **对现有系统扰动最小**：A 不需要改 `AUTH_USER_MODEL`，现有登录视图、
   Session 结构、模板变量（`request.session.info`）都可保留，可灰度切换。
4. **Django 能力仍可复用**：`Account` 通过 `PermissionsMixin`（或桥接到
   `Group`/`Permission`）即可获得细粒度权限，不必牺牲功能。

**同时明确**：A 的代价是"一段时间内两套模型并存"，因此必须**限定清理窗口**
（建议 1–2 个版本内完成），否则会演变成永久技术债。

## 5. Django 集成细节（路径 A）

### 5.1 认证后端

```python
# proto_account/backends.py（设计，本轮未启用）
class AccountBackend:
    def authenticate(self, request, login_name=None, password=None, role_hint=None):
        account = Account.objects.filter(
            login_name=login_name, is_active=True
        ).first()
        if account is None or not check_password(password, account.password):
            return None
        # role_hint 只用于"在哪个入口登录"，真正授权由 AccountRole 决定
        if role_hint and not account.roles.filter(role=role_hint).exists():
            return None
        return account

    def get_user(self, user_id):
        return Account.objects.filter(pk=user_id).first()
```

### 5.2 `request.user` 与 Session

- `django.contrib.auth.middleware.AuthenticationMiddleware` 依赖 `AUTH_USER_MODEL`
  与 `get_user`；路径 A 下 `request.user` 会是 `Account` 实例（需 `PermissionsMixin`）。
- 现有代码使用 `request.session['info']`（`id`/`name`/`type`），**无需改动**；
  可在切换期同时写入 `login()`，让两套机制并存。

### 5.3 登录名命名空间

原型实测：6 个账号中**跨类型撞号 0 例**（管理员 3 位数字、教师 7 位、学生 10 位，天然不重叠）。
但设计上仍需防御：

- 方案 1（推荐）：`login_name` 保持原始编号，**冲突时拒绝回填并报告**（原型已实现）；
- 方案 2：`login_name = f"{person_type}:{id}"`，登录时必须先选角色（现有 UI 已分角色入口）。

### 5.4 权限模型

| 动作 | codename | 默认授予 |
|---|---|---|
| 查看 | `view_*` | admin/teacher 相应范围 |
| 新增/修改/删除 | `add_*` / `change_*` / `delete_*` | admin |
| 重置密码 | `reset_password` | admin |
| 批量导入 | `import_data` | admin |
| 角色管理 | `manage_roles` | 超管 |
| **清表** | `dangerous_bulk_delete` | **无任何角色** |

对象级范围（学院/班级）由查询集过滤实现，不靠 URL 前缀。

## 6. 兼容与回滚设计

| 阶段 | 内容 | 回滚 |
|---|---|---|
| P1（本轮已做） | 新建 `Account`/`AccountRole`/`Profile`，旧表不动 | 删原型库/停用 app |
| P2 | 回填（幂等、`--rollback`、`--since`） | `--rollback` 删除回填行，旧表不动 |
| P3 | 双写：新建/改密同时写旧表与新表 | 关开关，回到旧路径 |
| P4 | 读路径切到 `Account`，旧表转只读 | 切回旧读路径 |
| P5 | 清理旧表（需独立评审） | 依赖备份恢复 |

**关键**：P3/P4 必须有"一致性校验任务"（对比两套表的账号数、密码哈希、角色），
否则无法证明双写正确。

## 7. 待决问题（需要下一轮决定）

1. `Account` 是否启用 `PermissionsMixin`（影响 `request.user.has_perm` 可用性）；
2. 是否需要"一人多号合并"（同一人既有教师号又有管理员号的场景）；
3. 密码策略是否统一（教师/管理员是否也受 6-10 位限制）；
4. 旧表保留期限与清理责任人。

## 8. 结论

| 项 | 结论 |
|---|---|
| 推荐架构 | **路径 A（独立 Account + 自定义 Backend），三步渐进** |
| 正式切换 | **NOT DONE**（明确列为受控后续任务） |
| 证据基础 | 隔离库 6 账号回填 + 9 项失败注入 + 一致性校验 |
| 路径 B | 保留为长期终态选项，但当前缺乏运行证据，不采纳 |
