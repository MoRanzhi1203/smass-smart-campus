# SMASS 变更清单（Change Log）

- 基线：`4bddb70`（原始状态）
- 变更统计：**修改 33 个文件、新增 22 项（含目录）、删除 1 个文件**
- 兼容性原则：外部 URL 路径全部保持不变；仅内部实现、模板渲染方式与安全策略发生变化

---

## 1. 新增文件

| 文件 | 作用 |
|---|---|
| `smass/env_loader.py` | 极简 `.env` 读取（无第三方依赖，`setdefault` 不覆盖真实环境变量） |
| `smass/urls_account.py` / `urls_admin.py` / `urls_student.py` / `urls_teacher.py` | 路由按业务域拆分，全部命名路由 |
| `app01/services/__init__.py` | 服务层包 |
| `app01/services/accounts.py` | **密码唯一写入路径**：官方哈希、旧 MD5 兼容升级、会话建立/销毁、登录限速、审计日志 |
| `app01/services/crud.py` | 显式搜索字段、行详情（屏蔽密码）、按模型删除、`endpoints` 命名路由生成 |
| `app01/services/imports.py` | Excel 导入：先校验后入库、单事务、错误清单、统一随机口令 |
| `app01/utils/authz.py` | `admin_required` / `student_required` / `teacher_required` 装饰器 |
| `app01/migrations/0004_alter_admin_password_alter_student_password_and_more.py` | 三个账号表 `password` 64 → 128 |
| `app01/management/commands/seed_dev.py` | 幂等开发种子数据 |
| `app01/tests/`（`__init__` / `helpers.py` / 4 个用例文件） | 79 个自动化测试 |
| `templates/admin/import_result.html` | 导入结果页（成功/失败清单 + 一次性口令只显示一次） |
| `scripts/check.ps1` | 质量门禁（check + 迁移一致性 + 测试 + 部署审计） |
| `scripts/db_inspect.py` | 数据库只读巡检（不输出密码） |
| `requirements.txt` / `environment.yml` | 依赖锁定与可复现环境 |
| `.env.example` / `.gitignore` / `README.md` | 配置模板、忽略规则、使用文档 |
| `docs/*`（6 份） | 审计、变更、测试、迁移、安全、R2 设计 |

## 2. 删除文件

| 文件 | 原因 |
|---|---|
| `app01/tests.py` | 被 `app01/tests/` 包取代，避免模块/包同名冲突 |

---

## 3. 逐文件变更

### 3.1 配置与入口

**`smass/settings.py`**（重写）
- 全部配置改为环境变量：`DJANGO_*` / `DB_*`，代码内不再出现真实口令与可用于生产的密钥。
- `'POST': 3306` → `'PORT'`（拼写修正）。
- `DEBUG=False` 且未提供 `DJANGO_SECRET_KEY` 时**启动即报错**，避免"生产误用开发密钥"。
- 新增 MySQL `OPTIONS`（`utf8mb4` + `STRICT_TRANS_TABLES`）与 `TEST` 库配置。
- `TIME_ZONE` `UTC` → `Asia/Shanghai`（与中文本地化意图一致）。
- `SESSION_COOKIE_AGE` 统一为 24 小时（原注释写"7 天"、实现是 1 天）。
- 新增 `LOGGING`（`smass.audit` 通道 + 轮转文件 `logs/smass.log`）。
- 非 DEBUG 时自动收紧 `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` / `SECURE_CONTENT_TYPE_NOSNIFF` 等。
- **兼容性**：本地需存在 `.env` 或环境变量提供 `DB_PASSWORD`，否则连接失败（已在 `.env.example` 与 README 说明）。

**`smass/__init__.py`**
- 驱动适配：优先 `MySQLdb`，缺失时用 PyMySQL 并声明 `version_info=(1,4,6)` 以通过 Django 5.2 的版本断言。

**`smass/urls.py`**
- 由 211 行集中式改为 `include()` 四个模块；`/media/` 保留（仅开发）。
- **兼容性**：所有业务路径逐条保持不变。

### 3.2 模型

**`app01/models.py`**
- 删除 `Admin` / `Student` / `Teacher` 的 `save()` 覆盖（原为无条件 MD5）。
- `password` `max_length` 64 → 128。
- `connect_instructors()`：`instructor` → `counsellor`；`position_id=1` → `position__name='辅导员'`；`save()` → `save(update_fields=[...])`。
- `Admin` 补 `__str__`（便于日志/调试）；移除未使用的 `AbstractUser` 导入。
- **兼容性**：`save()` 不再自动哈希，任何外部脚本若依赖旧行为会失效（现已无此依赖）。

### 3.3 表单

**`app01/form/account.py`**（重写）
- 删除 `clean_password` 的 MD5；新增 `TeacherLoginForm`；`clean_id` 去空白校验。

**`app01/form/admin_inter.py`**（重写）
- 密码改为**非模型字段**（`required=False`、`render_value=False`）：避免 `construct_instance` 把空值写回模型。
- 账号类表单补齐主键 `id`；编辑时 `disabled`。
- `TeacherModelForm` 显式字段清单，排除 through M2M `position`。
- `optional_model_fields` 放开 `null=True` 字段的必填约束。
- `ClassesModelForm.counsellor` 允许留空（后分配）。

### 3.4 视图

**`app01/views/account.py`**（重写）
- 三角色共用 `_handle_login`；失败信息统一"账号或密码错误"；`url_has_allowed_host_and_scheme` 防开放重定向。
- 登录限速（5 次 / 锁定 300 秒）。
- 移除 `print(admin_object)` 等调试输出。

**`app01/middleware/auth.py`**（重写）
- `/teacher/*` 不再 `pass`；AJAX 未登录返回 403 JSON 而非 302；跳转携带 `next`；移除调试 `print`。

**`app01/views/admin/*.py`（9 个，全部重写）**
- 统一：`@admin_required` + `@require_POST`（写操作）、`crud.apply_search`、`crud.row_detail_dict`（屏蔽 password）、`crud.delete_by_pk`、`endpoints` 注入。
- 修复：班委 `name_en`、两处误传 `models.Department`、三处非法搜索字段、管理员重置密码路由。
- 新增：`all_delete` 需 `confirm=YES` + POST；`admin_delete` 禁止删除自己。
- 导入改为调用 `services/imports.py`，渲染 `import_result.html`。

**`app01/views/student/st_users_profile.py`**
- 改密走 `accounts.verify_password` / `set_password`；业务规则（6-10 位、字母数字）保留。

**`app01/views/student/st_classes_list.py`**
- 作用域收窄为"本人班级"，不再用 `classes__in=<values 子查询>`。

**`app01/views/teacher/te_basic.py`**
- 加 `@teacher_required`；读取并展示教师本人信息。

### 3.5 模板

**`templates/layout/admin.html`**（重写 JS 部分）
- 接口地址来自 `endpoints`（`reverse()`）+ `json_script`，不再用 `name_en` 拼 URL。
- 删除：GET → POST，并统一 `X-CSRFToken`。
- 新增：新建账号的"初始密码"一次性提示；重置密码展示新口令。
- 未实现入口（楼栋、个人资料）标注"未启用"。

**`templates/admin/*.html`（8 个）**
- 下载模版链接改用 `{{ endpoints.template }}`。
- 部门/团学干部/班委三页隐藏未实现的批量导入入口。

**`templates/login/index.html`**（重写）
- 学生/教师入口指向各自的登录页（原学生入口直链 profile 会被中间件拦截）。
- 宿管/商家置灰标注"未启用"，消除 404 死链。

**`templates/login/login.html`**
- 新增 `next` 隐藏域、锁定提示、`form.id.errors`（原为 `form.username.errors`，字段不存在）。

**`templates/teacher/basic.html`**（重写）
- 由 10 行占位页改为教师信息展示页 + 注销入口。

### 3.6 工具

**`app01/utils/encrypt.py`**
- `md5()` 增加可选 `secret_key`（用于校验历史哈希）；文档明确"只读兼容，不得写入"。

### 3.7 数据库

- 新增迁移 `0004`：三个 `password` 字段 64 → 128（仅 `AlterField`，无数据风险）。
- 开发库 `smass` 已执行 `migrate`（26 表）。
- `seed_dev` 已执行两次：首次 26 项新建，第二次 0 新建 / 26 复用（幂等）。

---

## 4. 行为变化（用户可见）

| 场景 | 变化 | 原因 |
|---|---|---|
| 编辑账号资料 | 密码框不再回显任何内容，留空即不改密码 | 原实现把哈希回显并二次哈希，导致账号失效 |
| 重置密码 | 生成随机口令并在弹窗中**只显示一次** | 原"身份证后六位"既是弱口令又与双重哈希冲突 |
| 新建账号 | 不填密码则随机生成并一次性提示 | 消除固定初始口令 |
| 批量导入 | 成功后进入结果页；失败则整批不写入并列出"第 N 行 + 原因" | 消除静默半成功 |
| 删除行 | 由 GET 改 POST（前端无感知） | CSRF 与预取防护 |
| 搜索 | 部门/干部页搜索不再 500 | 字段映射修正 |
| 登录 | 教师有独立登录入口；连续失败 5 次锁定 5 分钟 | 补齐鉴权 + 限速 |
| 首次登录 | 仍使用一次性初始口令，**未强制改密**（见安全报告遗留项） | 缺三端改密界面 |

## 5. 兼容性风险

1. **外部脚本若直接 `obj.save()` 期望密码被哈希**：现在不会。必须改用 `services/accounts.set_password`。仓库内已无此类调用（已 grep 确认）。
2. **若有人用 GET 调删除接口**：返回 405。同仓前端已同步改 POST。
3. **若部署环境没有 `.env` 且未设 `DB_PASSWORD`**：连接失败。这是有意的（不允许代码内硬编码口令）。
4. **旧 MD5 账号**：仍可登录，并在首次成功登录时自动升级为 PBKDF2。双重哈希的坏数据也可登录并修复。
5. **`TIME_ZONE` 改为 `Asia/Shanghai`**：日期字段展示会从 UTC 变为本地时间（+8）。

---

## 6. 本轮补充修订（round 1 复核）

复核阶段发现并修复 4 项上一轮遗漏，均已补测试：

| # | 问题 | 修复 | 测试 |
|---|---|---|---|
| S1 | `app01/utils/formatchange.py` 已无调用方，但 `row_resetPass` 仍执行 `md5(cardID[-6:])` 并写库——死代码里留着"写弱哈希"的入口 | 模块改为**纯委托**：`row_resetPass` → `accounts.reset_password`；`row_obtain` → `crud.row_detail_dict`（屏蔽密码）；`row_delete` → `crud.delete_by_pk`。模块内已无任何哈希代码 | `test_compat_tools.LegacyToolCompatTests`（5 例） |
| S2 | 管理员列表页无"重置密码"按钮，后端 `admin/admin/resetPass/` 无 UI 入口 | `templates/admin/admin.html` 增加 `.btn-reset`，复用 layout 通用 JS | `test_admin_list_has_reset_password_button` |
| S3 | 管理员列表页"批量导入"按钮无 `id`、模块也无 `multi` 接口，点击无效 | 移除该按钮并注明原因 | `test_admin_list_has_no_bulk_import_button` |
| S4 | `templates/admin/building.html` 为孤立模板（无路由、无引用） | 删除 | — |

修订后全量回归：**87/87 通过**（原 79 + 新增 8）。