# SMASS 集成开发入口（R10 管理 + R11–R20 业务）

> 状态：**已完成并实测**
> 配置：`smass.settings_integrated_dev`、`smass.urls_integrated_dev`、`smass/dev_hub.py`
> 初始化：`scripts/integrated_dev_bootstrap.py`
> 启动：`python manage.py runserver 127.0.0.1:8020 --settings=smass.settings_integrated_dev`

## 1. 根因：为什么启动后看到的是数年前的旧界面

| 证据 | 结论 |
|---|---|
| `smass/settings.py` 的 `ROOT_URLCONF = 'smass.urls'` | 默认入口就是旧系统 |
| `smass/urls.py` 只 include `urls_account` / `urls_admin` / `urls_student` / `urls_teacher` | 只有 app01 三端，没有 R4–R20 |
| `smass/settings_integrated_dev.py` 之前不存在 | R10/R20 各自只有独立 settings，从未合并 |
| 上一轮为了"能点开看看"，用了 `smass.settings` + `smass_demo` 库 | **把旧系统当成新系统启动了**，这是我的错误 |

旧系统的实际指征（实测）：数据库 `smass` 26 张表，全部是 `app01_*` / `auth_*` / `django_*`，
没有 `r21_account_account`、`smass_organization_*` 等新模型表。

## 2. R10 / R20 独立环境验证（先证明它们本身可用）

### R10 统一管理后台（`smass.settings_r10` → 库 `smass_r10_release`，72 表）

```powershell
python manage.py runserver 127.0.0.1:8040 --settings=smass.settings_r10
```

| 检查 | 结果 |
|---|---|
| 匿名 `/r10/` | 200（R10 原设计允许浏览导航页，页面显示"未登录"） |
| 匿名 `/r4/units/` | 403（有权限保护） |
| 登录（`admin` / 重置后密码） | 302 → `/r21/home/` → `/r10/` |
| `/r10/`、`/r4/units/`、`/r4/students/`、`/r5/years/`、`/r6/tasks/`、`/r7/dashboard/`、`/r9/status/` | 全部 200 |

### R20 多角色门户（`smass.settings_r20` → 库 `smass_r20_portal`，48 表）

```powershell
python scripts/integrated_dev_bootstrap.py --target r20
python manage.py runserver 127.0.0.1:8030 --settings=smass.settings_r20
```

| 检查 | 结果 |
|---|---|
| 匿名 `/r20/` | 302 → `/r21/login/?next=/r20/` |
| 登录 | 302 → `/r21/home/` |
| `/r20/`、`/r20/admin/` | 全部 200 |

## 3. 集成入口设计

### 3.1 单一数据库

`smass_integrated_dev`（**127 张表**），由 `scripts/integrated_dev_bootstrap.py` 一键重建：
建库 → `migrate`（R21/R22 账号 + R4–R9 + R11–R20 全部 app）→ 灌合成数据。
**不合并任何独立库**，也不把"能跳转"当成"已合并"。

### 3.2 统一登录与首页

| 路径 | 作用 |
|---|---|
| `/` | 302 → `/hub/` |
| `/hub/` | 统一首页：按角色渲染模块卡片；未登录 → `/r21/login/?next=/hub/` |
| `/r21/login/`、`/r21/logout/` | 统一登录/退出（R21 账号体系） |
| `/r21/home/` | 302 → `/hub/`（覆盖 R10 原有的"跳 `/r10/`"行为） |

### 3.3 路由整合（复用，不重写页面）

- R10 的完整路由（`urls_r10`：r4–r9 + r21 登录/改密）**原样复用**；
- R11 路由在 `urls_r11` 内联定义，集成配置过滤掉其登录/登出后合并；
- R16–R20 用 `include` 挂到 `/r16/`–`/r20/`，命名空间 `r12`–`r20` 互不冲突；
- 所有 URL 名在本文件内唯一，未与 `urls_r10` 的 `r21_login` 等重名；
- `/r10/` 在集成配置中额外包了 `login_required`（独立 R10 配置保持原样）。

### 3.4 角色差异（实测）

| 角色 | `/hub/` | `/r10/` | `/r12/placement/` | `/r11/plan/` | `/r11/timetable/teacher/` | `/r11/timetable/student/` |
|---|---|---|---|---|---|---|
| 系统管理员 | 200 | 200 | 200 | 200 | 200 | 200 |
| 学院管理员 | 200 | 200 | 200 | 200 | — | — |
| 教师 | 200 | 200 | 403 | **403** | 200 | — |
| 学生 | 200 | 200 | **403** | — | — | 200 |

hub 卡片也会按角色改指向：教师进"R11 排课与课表"落到教师课表，学生落到学生课表。

## 4. 启动命令（可复现）

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

# 1) 首次或重建数据（删库重来，全部合成数据）
& $py scripts\integrated_dev_bootstrap.py

# 2) 启动统一入口
& $py manage.py runserver 127.0.0.1:8020 --settings=smass.settings_integrated_dev
```

| 账号 | 密码 | 角色 |
|---|---|---|
| `dev_admin` | `Smass#2026` | 系统管理员 |
| `dev_college` | `Smass#2026` | 学院管理员 |
| `dev_teacher` | `Smass#2026` | 教师 |
| `dev_student` | `Smass#2026` | 学生 |
| `dev_counselor` | `Smass#2026` | 教师（辅导员身份） |

## 5. 验收证据

### 5.1 页面矩阵（管理员登录后，全部 200）

`/hub/`、`/r10/`、`/r4/import/`、`/r4/units/`、`/r4/students/`、`/r5/enroll/`、`/r5/years/`、
`/r6/tasks/`、`/r7/dashboard/`、`/r9/status/`、`/r11/plan/`、`/r12/placement/`、`/r13/sessions/`、
`/r14/activities/`、`/r15/clubs/`、`/r16/rooms/`、`/r17/forum/`、`/r18/bills/`、`/r19/orgs/`、`/r20/`

### 5.2 自动化测试

```powershell
& $py manage.py test smass_portal.tests.test_integrated_dev --settings=smass.settings_integrated_dev --noinput
```

**10 例全部 OK**（9 个 Django 客户端用例 + 1 个 Chromium 端到端：登录 → hub → `/r10/` → `/r12/placement/`）。

同一测试文件在 `smass.settings_r20` 下自动跳过（`@skipUnless(IS_INTEGRATED)`），
所以 `smass_portal` 套件在 R20 配置下仍是 36 例 OK。

### 5.3 旧系统兼容

- `smass.settings.ROOT_URLCONF` 仍为 `smass.urls`（有测试断言）；
- `smass/urls.py`、`smass/settings.py`、正式入口、认证切换状态**零改动**；
- 想继续看旧系统：`python manage.py runserver 127.0.0.1:8000 --settings=smass.settings_demo`
  （`smass_demo` 库是正式库的只读 dump 副本）。

### 5.4 正式库零写入

| 时点 | 指纹 |
|---|---|
| 集成开发前（FINAL） | `2127d05333a92e4a9cec37aac93ef6ea2e07756d5248340cb75fc0bf96d25bb3` |
| 集成开发后 | `2127d05333a92e4a9cec37aac93ef6ea2e07756d5248340cb75fc0bf96d25bb3` |

**完全一致**，26 表，写入 0、迁移 0。

## 6. 已知边界

1. R12–R19 在集成库中**只有账号/组织/学籍/学年课程/流程/指标**这些基础数据，
   各业务模块自身的业务数据（分班规则、考勤场次、活动、账单…）为空，
   页面可打开、列表为空，需要按需在各模块页面内创建；
2. R22 身份桥接中间件在集成配置中被 R4 链移除（与 R10 一致），
   统一身份走 R21 账号 + 角色组；
3. 集成配置 `DEBUG=True`、`ALLOWED_HOSTS=['*']`，**仅限本机开发**，禁止用于生产；
4. 旧系统（app01）与集成系统的账号体系不同：旧系统用 `app01_admin/student/teacher` 三表，
   集成用 `r21_account`，两者未做数据级迁移（本次只保证入口隔离、互不破坏）。
