# SMASS R2+ 架构方案（Architecture Proposal）

- 状态：**仅方案，本轮不做高风险重构**
- 前置：R0–R1 已完成（认证收敛、权限双层、CRUD 修复、迁移与 79 项测试）
- 原则：保持 Django 模块化单体；优先兼容现有 URL 与数据结构；每一步都可独立回滚

---

## 1. 统一 Account / Role / Permission

### 1.1 现状问题

| 问题 | 现状 |
|---|---|
| 三张独立账号表 | `Admin` / `Student` / `Teacher` 各自有 `password`，逻辑重复三份 |
| 无法多角色 | 一人若同时是"教师 + 管理员"，必须建两个账号 |
| 无细粒度权限 | 任一管理员可操作全部模块，包括删除其他管理员、清空学生表 |
| 认证分支 | 登录视图按"角色 → 模型"硬映射（`_LOGIN_CONFIG`） |

### 1.2 目标模型

```
Account
  id (uuid)            # 统一登录主体
  login_name (unique)  # 学号/工号/管理员号
  password             # 统一哈希
  is_active
  must_change_password
  last_password_change_at
  failed_attempts / locked_until   # 从 Session 限速升级为持久化限速

Role (枚举/表)
  ADMIN / TEACHER / STUDENT / HOUSEMASTER / BUSINESS

AccountRole        # 多对多：一个账号可多角色
  account, role, granted_at, granted_by

PersonProfile      # 人员业务信息（与登录分离）
  account (1:1)
  person_type: STUDENT | TEACHER | ADMIN
  ...

StudentProfile     # 学号、班级、身份证、住宿等
TeacherProfile     # 工号、院系、职务
```

### 1.3 兼容迁移（分三步，均非破坏性）

| 步骤 | 动作 | 可回滚 |
|---|---|---|
| P1 | 新建 `Account` / `AccountRole` / `StudentProfile` / `TeacherProfile`；**旧三表保持不动** | 删新表即可 |
| P2 | 写数据迁移：把 `Admin/Student/Teacher` 各灌成 `Account` + 对应 Profile；`password` 原样搬（已是 PBKDF2），`AccountRole` 按来源表授予 | 数据迁移可逆（保留 `legacy_source` 字段记录来源表/主键） |
| P3 | 认证切换到 `Account`（登录查 Account，业务查 Profile）；旧表改为**只读视图或幽灵表**保留一个版本周期 | 把 `AUTH_ACCOUNT_MODEL` 开关切回旧路径 |

### 1.4 是否改用 `AUTH_USER_MODEL`

**建议：是，但要按 P1–P3 渐进，不要一次性强切。**

理由：
- Django 的 `AUTH_USER_MODEL` 一旦在首次迁移后更改，官方不建议（`swap` 极难回滚）；
- 本项目已迁移 4 个版本，可行路径是**新建独立 `Account` 模型 + 自定义认证后端**，
  而不是把 `Student` 改造成 `AUTH_USER_MODEL`；
- 自定义认证后端 `SmassAccountBackend` 只需实现 `authenticate(request, login_name, password, role_hint)` 与 `get_user`。

**验收标准**：
- 同一账号可同时以 `TEACHER` 与 `ADMIN` 登录，Session 内记录**激活角色**；
- 旧 URL 与登录入口行为不变；
- 旧三表的密码哈希可原样迁移（不重新哈希）。

### 1.5 权限（RBAC）

- 用 Django `Group`/`Permission`（模型级 `add/change/delete/view`）作为**底座**，避免自造一套；
- 业务语义权限（如"可重置密码"、"可批量导入"、"可清表"）用自定义 `Permission`（`codename`）表达；
- 视图层从 `@admin_required` 升级为 `@permission_required('app01.reset_password')`；
- `all_delete`（清表）单独授予 `dangerous_bulk_delete`，默认不给任何角色。

---

## 2. 组织机构与人员信息分离

### 2.1 现状问题

- `Classes` 同时承担"组织单元"和"辅导员归属"两个职责（`counsellor` FK）；
- `Major.college`、`Classes.major`、`Classes.grade` 是"组织树"，但 `Student.classes` 直接指向班级，
  历史班级变更会导致"当前班级"与"历史班级"混淆；
- `Nation` / `Building` / `Dormitory` / `DormitoryNumber` 是死表（0 行、无代码引用）。

### 2.2 目标

```
Org 维度（相对静态）
College ─┬─ Major ─┬─ Grade ── Classes
         │         └─ (可选) TeachingGroup
         └─ Department（团学组织）

Person 维度（相对动态）
Account → StudentProfile ── enrollment（入学年份、学制、状态）
                        └─ StudentEnrollment（班级归属，带起止日期）

Housing
Building ── Room ── BedAssignment（学生/床位，带起止日期）
```

要点：
- **班级归属历史化**：`StudentEnrollment(student, classes, started_on, ended_on)`，替代 `Student.classes` 直接字段（旧字段保留为"当前班级"冗余，用于列表性能与兼容）；
- **宿舍从"字符串字段"升级为实体**：`Student.building/dormitory` 目前是 `CharField(max_length=3)`，无法表达楼栋-房间-床位层级；
- **死表处理**：`Nation` 已改为字符串字段，`Building/Dormitory/DormitoryNumber` 若随宿舍模块启用则复用，否则在 R3 删除（需先 grep 确认零引用）。

### 2.3 迁移策略

1. 先建新表与新关系（不动旧字段）；
2. 数据迁移把 `Student.classes` 灌入 `StudentEnrollment`（`started_on` 取入学年份，`ended_on=NULL`）；
3. 读路径切到新表，`Student.classes` 保留为**缓存字段**由信号同步；
4. 稳定一个版本后再删旧字段。

---

## 3. 任职模型 `StudentPositionAssignment`

### 3.1 现状问题

| 模型 | 约束 | 后果 |
|---|---|---|
| `LeagueCadres` | `id` 是 `OneToOneField(Student)` 主键 | 一人只能有**一个**团学职务 |
| `ClassCommittee` | 同上 | 一人只能有**一个**班委职务 |
| 两者之间 | 无互斥也无关联 | 同一人可同时是班委和团干（合理），但无法记录任期 |

### 3.2 目标模型

```python
class StudentPositionAssignment(models.Model):
    student = FK(Student)
    position = FK(Position)              # 或分类型：COMMITTEE / LEAGUE
    scope_type = CharField(choices=[('class','班级'),('department','部门'),('college','学院')])
    scope_id = PositiveIntegerField()    # 班级/部门主键
    started_on = DateField()
    ended_on = DateField(null=True, blank=True)
    appointed_by = FK(Account, null=True)
    note = TextField(blank=True)

    class Meta:
        constraints = [
            # 同一人 + 同一职务 + 同一范围，任期不得重叠
            UniqueConstraint(fields=['student','position','scope_type','scope_id','started_on'],
                             name='uniq_assignment_start'),
        ]
        indexes = [Index(fields=['student','ended_on'])]
```

### 3.3 任期重叠规则

- 应用层校验（`clean()` + 事务内 `select_for_update`）：
  同一 `(student, position, scope)` 下，新区间 `[started_on, ended_on]` 不得与既有区间相交；
- 未结束的任职（`ended_on IS NULL`）视为 `+∞`；
- 允许同一人**同时**担任不同范围/不同职务（如"班长"+"团总支委员"）；
- 数据库层用唯一约束兜底"同一人同一职务同一天不能重复上任"。

### 3.4 迁移

1. 新建表；
2. 把 `LeagueCadres` / `ClassCommittee` 现有行灌入（`started_on` 用迁移日期，`ended_on=NULL`，`scope` 取部门/班级）；
3. 两旧表保留为只读视图（或保留表一个周期）；
4. 后台管理页改为新模型的 CRUD（可按"当前在任"筛选）。

---

## 4. 未来功能边界与优先级

| 优先级 | 模块 | 价值 | 依赖 | 本轮是否可动 |
|---|---|---|---|---|
| P0 | 统一 Account + RBAC | 安全与可维护性底座 | 无 | ❌ R2 首项 |
| P0 | 首次登录强制改密 | 消除"管理员知晓用户口令" | Account（`must_change_password`） | ❌ 依赖 P0-1 |
| P1 | 任职历史（§3） | 解决一人多职/任期追溯 | 班级/部门稳定 | ❌ |
| P1 | 学生事务（请假/处分/奖励） | 核心业务扩展 | Account + 班级 | ❌ |
| P1 | 宿舍管理实体化 | 替换字符串字段 | Org 分离 | ❌ |
| P2 | 通知/公告 | 触达能力 | Account | ❌ |
| P2 | 系统审计（操作留痕查询界面） | 合规 | 审计日志已具备（`smass.audit`） | 部分可动 |
| P3 | 数据分析（在校生、职务分布） | 决策支持 | 数据模型稳定 | ❌ |
| P3 | 商家/宿管端 | 完整角色闭环 | Account + RBAC | ❌ |

**不建议**当前引入：Celery/Redis（无异步刚需）、微服务（单体足够）、前后端分离（团队与收益不匹配）。

---

## 5. 前端 UI / 组件库统一

### 5.1 现状问题

- 后台：Bootstrap 3.4.1 + jQuery 3.7.1 + 手写模态框 JS（8 个通用函数）
- 学生端：Bootstrap 5.3.2 + NiceAdmin 模板 + `simple-datatables` + `TinyMCE`
- 两套栅格/类名体系并存，样式与交互不一致；后台表单靠 `#id_字段名` 约定，脆弱

### 5.2 方案

| 层 | 建议 |
|---|---|
| 组件库 | 统一到 **Bootstrap 5**，后台改用 `bootstrap.bundle.js`（自带 Modal，去掉 jQuery 依赖） |
| 表格 | 统一 `simple-datatables` 或服务端分页二选一：**后台保留服务端分页**（数据量可控、SEO/书签友好），学生端可用前端表格 |
| 表单渲染 | 用 Django 表单 `{{ field }}` + 统一模板片段（`_form_field.html`），不再靠 `#id_*` 手工映射 |
| 接口调用 | 保留本轮引入的 `endpoints`（命名路由 → JSON）机制，替换为 `fetch()` + 统一错误处理 |
| 布局 | 抽 `layout/base.html`，后台/学生端只换侧栏与导航 |
| 渐进路径 | 先做"后台 9 个 CRUD 页"（同构、风险低），再做学生端个人主页 |

### 5.3 不建议

- 不引入 React/Vue SPA：当前页面同构度高，收益低于改造成本；
- 不引入微前端；不重写全部模板（R1 已保证功能正确，UI 属体验优化）。

---

## 6. 兼容性、数据回填、回滚与验收

### 6.1 总原则

1. **加表不加列，加列不删列**：新结构先旁挂，读路径切换后再清理旧字段；
2. **双写一个周期**：新旧结构同时写，旧路径仍可读，便于回滚；
3. **每步一个迁移**，禁止一个大迁移里做多件事；
4. **每步都有可执行的验收脚本**（管理命令或测试）。

### 6.2 数据回填（backfill）通用模式

```python
# app01/management/commands/backfill_xxx.py
class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=500)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--since-id', type=int, default=0)  # 断点续跑
```

要求：
- 支持 `--dry-run` 只统计不写库；
- 分批 + 每批一个事务，可断点续跑；
- 结束时打印 `processed / created / skipped / failed` 四项计数；
- 失败行写入 `logs/backfill_failed_<ts>.json`（不含敏感字段）。

### 6.3 回滚策略

| 变更类型 | 回滚方式 |
|---|---|
| 新增表/字段 | `migrate app01 <上一个版本>`（Django 自动反向操作） |
| 数据回填 | 回填命令自带 `--rollback`（按 `legacy_source` 删除新表中由回填产生的行） |
| 认证切换 | 配置开关 `AUTH_BACKEND=legacy|account`，改回即恢复旧路径（旧表未删） |
| 前端切换 | 模板 `{% if ui_v2 %}` 灰度；CSS/JS 走静态文件版本号 |

### 6.4 迁移验收标准（每项必须全部满足）

1. `manage.py check` 0 issues；
2. `makemigrations --check --dry-run` 无变化；
3. 全量测试通过，且**新增用例覆盖新模型的关键约束**（如任期不重叠、一人多角色）；
4. 在隔离库 `test_smass` 上"从零迁移 → 种子 → 测试 → 销毁"整链路通过；
5. 回填命令 `--dry-run` 与实跑计数一致；
6. 旧 URL 与旧登录入口行为不变（回归用例守护）；
7. 性能基准：主要列表页查询数不高于改造前（用 `assertNumQueries` 固化）。

### 6.5 里程碑建议

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | Account + RBAC + 强制改密（§1） | 最大风险项，优先 |
| M2 | 组织/人员分离 + 任职历史（§2、§3） | 依赖 M1 的 Profile |
| M3 | 前端统一（§5）+ 审计查询界面 | 可与 M2 并行 |
| M4 | 学生事务 / 宿舍 / 通知（§4） | 业务扩展 |
| M5 | 字符集 `utf8mb4` 转换 + 数据库备份演练 + `pip-audit` 接入 | 运维加固，可提前 |

---

## 7. 本轮遗留项对应的 R2 落点

| 遗留 | R2 落点 |
|---|---|
| 首次登录强制改密未实现 | §1.1 `must_change_password` + §6.5 M1 |
| 无细粒度权限 | §1.5 RBAC |
| 库/表字符集 `utf8` | §6.5 M5 |
| 数据库无自动备份 | §6.5 M5 |
| 未做依赖漏洞扫描 | §6.5 M5 |
| `Nation/Building/Dormitory` 死表 | §2.2 宿舍实体化时复用或 R3 清理 |
| Bootstrap 3/5 混用 | §5 |
