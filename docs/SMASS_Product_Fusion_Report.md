# SMASS 产品融合重构报告（三端统一系统）

> 状态：**三端可运行、可操作，验收通过**
> 配置：`smass.settings_product` / `smass.urls_product`
> 隔离库：`smass_product_dev`（正式库 `smass` 全程只读）
> 日期：2026-10-31

---

## 1. 交付结论

SMASS 现在是**一套系统**，而不是三套独立产品：

| 维度 | 结果 |
|---|---|
| 产品形态 | 一个 Django 项目、一个 URLConf、一套模板与设计系统 |
| 身份 | 一个统一登录入口 `/login/`，登录后由后端按角色落地 |
| 业务数据 | 一个隔离库 `smass_product_dev`，复用 R4–R20 全部模型与服务 |
| 角色界面 | 学生工作台 `/student/`、教师工作台 `/teacher/`、管理控制台 `/admin/` |
| 研发外壳 | `/r10/`、`/hub/` 只做重定向；导航中不出现 R10/R20 等版本编号 |
| 原有功能 | `/r4/`–`/r9/`、`/r11/`–`/r20/` 深层功能页按原路径保留 |
| 正式库 | 26 表 / 111 列，指纹 `b914b39c…` 前后一致，写入 0 |

产品页面共 **48 个**（学生 15 / 教师 13 / 管理 20），全部由统一 shell 渲染。

---

## 2. 架构

```
┌──────────────────────────────────────────────────────────────┐
│  统一登录 /login/  →  后端按角色落地（管理 > 教师 > 学生）      │
└───────────────┬──────────────────┬──────────────────┬────────┘
                │                  │                  │
        ┌───────▼──────┐   ┌───────▼──────┐   ┌───────▼────────┐
        │ 学生工作台    │   │ 教师工作台    │   │ 管理控制台      │
        │ /student/    │   │ /teacher/    │   │ /admin/         │
        └───────┬──────┘   └───────┬──────┘   └───────┬────────┘
                └──────────────────┼──────────────────┘
                                   │  同一套设计系统 shell
                    ┌──────────────▼───────────────┐
                    │ smass_workspace（产品层）      │
                    │ 导航 / 守卫 / 聚合服务 / 模板   │
                    └──────────────┬───────────────┘
        ┌───────────────┬──────────┴──────────┬────────────────┐
        │ r21_account   │ smass_organization  │ smass_academic │
        │ 统一身份/角色  │ 组织/学籍            │ 学期/课程/教学班 │
        ├───────────────┼─────────────────────┼────────────────┤
        │ smass_sched.  │ smass_attendance    │ smass_activit. │
        │ 排课/课表      │ 考勤/请假/补签       │ 活动/志愿/学分  │
        ├───────────────┼─────────────────────┼────────────────┤
        │ smass_clubs   │ smass_facilities    │ smass_finance  │
        │ 社团/任职      │ 场地/预约/审批       │ 账单/缴费/退费  │
        ├───────────────┼─────────────────────┼────────────────┤
        │ smass_forum   │ smass_workflow      │ smass_operat.  │
        │ 论坛/公告      │ 流程/待办/通知       │ 监控/告警/探针  │
        └───────────────┴─────────────────────┴────────────────┘
                                   │
                    统一隔离库 smass_product_dev（127 表）
```

### 2.1 为什么不是"三套产品"

- **一个认证**：R21 `Account` 是唯一身份；`app01` 旧三表不再承载登录。
- **一份业务数据**：请假、预约、账单等对象只有一张表，三端读写同一行。
- **一个设计系统**：`static/workspace/app.css` + `templates/workspace/base.html`，
  三端只切换强调色（学生蓝 / 教师青 / 管理靛），不切换框架。
- **一处权限判定**：`smass_workspace/permissions.py` 是唯一守卫入口，
  服务端 403，而不是靠隐藏菜单。

### 2.2 与 R10 / R20 的关系

| 旧形态 | 产品中的处理 |
|---|---|
| R10 独立管理后台外壳 `/r10/` | 301/302 到 `/admin/`；R10 的功能页并入管理控制台导航 |
| R20 多角色门户 `/r20/` | 保留为深层功能页，不再作为入口 |
| dev_hub 研发门户 `/hub/` | 302 到 `/` |
| R11–R20 独立 settings | 不删除，作为各模块回归测试配置；产品统一使用 `settings_product` |

---

## 3. 三端界面

### 3.1 学生工作台（15 页）

| 页面 | 路由 | 真实数据来源 |
|---|---|---|
| 学习工作台 | `/student/` | 学期、今日课表、考勤率、待缴费用、待办、公告 |
| 我的课表 | `/student/timetable/` | `ScheduleEntry` + `Enrollment`（已发布 run） |
| 我的课程 | `/student/courses/` | `Enrollment` + `TeachingSection` + `TeachingAssignment` |
| 学籍信息 | `/student/record/` | `StudentRecord` + `StudentRecordChange` |
| 考勤与请假 | `/student/attendance/` | `AttendanceRecord` + `LeaveRequest` |
| 费用与账单 | `/student/fees/` | `Bill`（缴费写 `Payment`/`LedgerEntry`） |
| 场地预约 | `/student/bookings/` | `Room` + `RoomBooking` |
| 活动与志愿 | `/student/activities/` | `Activity` + `ActivityRegistration` |
| 志愿服务 | `/student/volunteer/` | `ActivityCredit` |
| 社团 | `/student/clubs/` | `Club` + `ClubMembership` |
| 学生组织 | `/student/organizations/` | `OrganizationUnit` + `OrganizationMembership` |
| 我的寝室 | `/student/dormitory/` | `StudentRecord.extra.dormitory`（历史档案只读回退） |
| 通知公告 | `/student/notices/` | `Announcement`（按受众过滤） |
| 通知中心 | `/notifications/` | `Notification` + `Announcement`（三端共用） |
| 个人中心 | `/profile/` | `Account` + 组织关系（三端共用） |

学生可执行的操作：提交请假、撤销请假、自助缴费、申请/取消场地预约、
报名/取消活动、申请入社。所有写操作都调用各模块服务函数，
因此冲突检测、状态机与审批规则与学生端页面共用同一套实现。

### 3.2 教师工作台（13 页）

| 页面 | 路由 | 说明 |
|---|---|---|
| 教学工作台 | `/teacher/` | 教学班、学生数、本周课时、待批请假、待办 |
| 我的课程 | `/teacher/courses/` | 本人教学班与选课人数 |
| 教学班 | `/teacher/sections/` | 班级名单（来自选课记录） |
| 我的课表 | `/teacher/timetable/` | `ScheduleEntry.teacher = 本人` |
| 考勤管理 | `/teacher/attendance/` | 发起场次、签到码、登记、结束 |
| 考勤登记 | `/teacher/attendance/<pk>/` | 逐人登记出勤/迟到/缺勤/请假 |
| 学生事务 | `/teacher/students/` | 本人教学班学生（对象级范围） |
| 学生档案 | `/teacher/students/<pk>/` | 选课、考勤、请假；越权 403 |
| 审批中心 | `/teacher/approvals/` | 请假、补签、流程待办、场地预约 |
| 负责班级 | `/teacher/classes/` | **仅辅导员**；范围来自组织关系 |
| 负责学生 | `/teacher/counselor/students/` | **仅辅导员** |
| 请假审批 | `/teacher/counselor/leaves/` | **仅辅导员** |
| 通知与公告 | `/teacher/notices/` | 按受众过滤 |

辅导员扩展不新建账号类型：教师账号被授予
`OrganizationMembership(role='counselor')` 后，教师端自动出现"辅导员工作"分组，
菜单与后端守卫同时生效。

### 3.3 管理控制台（20 页）

| 分组 | 页面 | 路由 |
|---|---|---|
| 总览 | 控制台总览 | `/admin/` |
| 身份与组织 | 用户账号 / 角色与权限 / 组织架构 | `/admin/users/`、`/admin/roles/`、`/admin/organizations/` |
| 学籍与教学 | 学籍管理 / 学籍异动 / 学年学期与课程 / 教学班与选课 | `/admin/records/` … `/admin/sections/` |
| 排课与资源 | 排课与课表 / 教室与场地 / 预约审批 | `/admin/scheduling/`、`/admin/facilities/`、`/admin/booking-approvals/` |
| 审批与工作流 | 待办与审批 / 流程定义 | `/admin/approvals/`、`/admin/workflows/` |
| 校园业务 | 活动管理 / 社团与学生组织 / 通知公告 | `/admin/activities/`、`/admin/clubs/`、`/admin/notices/` |
| 数据治理 | 数据导入导出 | `/admin/data-exchange/` |
| 运维与安全 | 运行监控 / 安全审计 / 系统配置 | `/admin/monitoring/`、`/admin/audit/`、`/admin/settings/` |

**超级管理员与普通管理员使用同一设计体系，权限严格不同**：

| 能力 | 系统管理员 | 学院管理员 |
|---|---|---|
| 数据范围 | 全局 | `scope_college` 对应学院子树 |
| 用户/角色写操作 | 可 | **403** |
| 系统配置与权限治理 | 可 | **403** |
| 活动发布/结束 | 可 | 只读 |
| 公告创建/发布 | 可 | 只读 |
| 学籍异动审批 | 可 | 可（限本院学生） |
| 请假 / 场地审批 | 可 | 可（限本院学生） |
| 监控 / 审计 / 数据交换 | 可 | 可（读） |

---

## 4. 统一设计系统

| 组成 | 实现 |
|---|---|
| 顶部栏 | 品牌、当前工作台、工作台切换、通知铃（未读数）、用户菜单、退出（POST） |
| 侧边栏 | 分组导航，数据驱动（`navigation.py`），当前项高亮与 `aria-current` |
| 页面布局 | `.ws-page-head`、`.ws-card`、`.ws-grid-*`、`.ws-stack` |
| 表单 | `.ws-field`、`.ws-input`、`.ws-select`、`.ws-textarea`、`.ws-form-actions` |
| 表格 | `.ws-table`（数字右对齐、操作列右对齐、空表提示） |
| 消息 | `messages` → `.ws-alert`（success/warning/error/info） |
| 空状态 | `.ws-empty`（图标 + 标题 + 说明 + 操作） |
| 交互规范 | 抽屉式移动端导航、表单防重复提交、`prefers-reduced-motion`、跳过导航链接 |
| 一致性 | 三端同一 CSS 文件、同一组件类名，仅 `--ws-accent` 变量不同 |

不采用 iframe、不采用三套前端框架、不保留外部产品外壳。

---

## 5. 权限模型与后端拒绝

### 5.1 守卫

```python
@require_kind('student')   # 未登录 → /login/?next=…；无角色 → HTTP 403
@require_kind('teacher')
@require_kind('admin')
@require_system_admin      # 管理端内的系统级页面
```

- 角色判定只看 `r21_account` 的角色（`system_admin` / `college_admin` /
  `teacher` / `student`），**不再用 `is_staff` 兜底**——否则教师账号会被
  误判为管理员（本轮修复的真实缺陷）。
- 登录后落地：管理端 > 教师端 > 学生端；无角色 → `/no-role/`（403 页面）。

### 5.2 对象级范围

| 角色 | 可访问学生范围 |
|---|---|
| 系统管理员 | 全部 |
| 学院管理员 | `scope_college` 对应的组织子树 |
| 辅导员 | 被授予 `role='counselor'` 的班级及其学生 |
| 教师 | 本人教学班内已选课学生 |
| 学生 | 仅本人 |

详情页（`/teacher/students/<pk>/`）与审批动作都调用同一判定；
不在范围内返回 403 页面，而不是 404 或空数据。

### 5.3 实测拒绝矩阵

| 访问者 | `/student/` | `/teacher/` | `/admin/` | `/admin/settings/` |
|---|---|---|---|---|
| 匿名 | 302 → 登录 | 302 → 登录 | 302 → 登录 | 302 → 登录 |
| 学生 | 200 | **403** | **403** | **403** |
| 教师 | **403** | 200 | **403** | **403** |
| 辅导员 | **403** | 200 | **403** | **403** |
| 学院管理员 | **403** | **403** | 200 | **403** |
| 超级管理员 | **403**（未持有学生角色） | **403** | 200 | 200 |

> 超级管理员不持有学生/教师角色时同样被拒绝——管理权限不等于数据权限。

---

## 6. 身份与数据

### 6.1 隔离环境

| 项 | 值 |
|---|---|
| 产品库 | `smass_product_dev`（127 表，可删库重建） |
| 初始化 | `python scripts/product_bootstrap.py` |
| 正式库 | `smass`，26 表 / 111 列，**只读** |

### 6.2 app01 历史数据迁移

`scripts/legacy_migration.py` 以正式库为**只读源**，把 app01 历史数据映射到统一模型：

| 源表 | 目标 |
|---|---|
| `app01_college` / `app01_major` / `app01_grade` / `app01_classes` | `OrganizationUnit` 树（同名学院复用，不产生重复） |
| `app01_department` | `OrganizationUnit(department)` |
| `app01_student` | `Account(student)` + `StudentProfile` + `StudentRecord` + `student` 角色 |
| `app01_teacher` | `Account(teacher)` + `TeacherProfile` + `teacher` 角色 + 学院关系 |
| `app01_admin` | `Account(admin)` + `system_admin` 角色 |
| `app01_classcommittee` / `app01_leaguecadres` | `OrganizationMembership`（班委/团学职务） |
| `classes.counsellor` | `OrganizationMembership(role='counselor')` |

关键设计：

- **密码哈希直接继承**（源为 `pbkdf2_sha256$`）；非 Django 格式则设为不可用密码并要求改密。
- **PII 默认不落地**：手机号掩码、身份证不迁移；需要原值必须显式设置
  `SMASS_MIGRATE_REAL_PII=YES_I_HAVE_AUTHORIZATION`。
- **幂等**：以 `LegacyAccountLink(source_table, source_pk)` 为锚点，重复执行不产生重复账号。
- **可回滚**：manifest 记录本批次对象；回滚删除本批次且无外部引用的对象，复用单元不动。
- **正式库只读**：迁移前后指纹必须一致（实测 `940a687d…` 前后相同）。

实测结果：源 3 学生 / 2 教师 / 1 管理员 / 2 学院 / 3 专业 / 3 年级 / 2 班级 / 2 部门
→ 目标 6 账号 / 3 学籍 / 8 组织单元 / 4 组织关系；回滚删除 3 学籍 / 6 账号 / 8 单元；
回滚后重新迁移并校验全部通过。

---

## 7. 验收证据

| 检查 | 结果 | 证据 |
|---|---|---|
| 三端页面冒烟（Django client） | PASS | `.local/evidence/product/smoke.json` |
| 三端真实浏览器（Chromium） | PASS，23 项检查 | `.local/evidence/product/e2e.json` + 15 张截图 |
| 管理员授权 → 用户落地变化 | PASS，8 项检查 | `.local/evidence/product/grant_check.json` |
| 教师审批 → 学生端状态同步 | PASS | E2E「学生端同步看到已批准」 |
| 管理员发布公告 → 学生端可见 | PASS | E2E「学生端看到管理员发布的公告」 |
| 越权后端拒绝 | PASS（403） | E2E 4 项 + 冒烟 5 项 |
| 历史迁移 + 回滚 + 再迁移 | PASS | `.local/evidence/migration/*.json` |
| 正式库零写入 | PASS（指纹一致） | `.local/evidence/product/formal_db_fingerprint.json` |
| 全量回归 | 见 §7.2 | `r10_full_regression.py` |

### 7.1 浏览器验收截图（节选）

截图目录：`.local/evidence/product/screenshots/`

| 文件 | 内容 |
|---|---|
| `00_login.png` | 统一登录入口 |
| `01_student_home.png` | 学生工作台（课表/考勤/费用/待办/公告） |
| `02_student_timetable.png` | 学生课表 |
| `05_teacher_home.png` | 教师工作台 |
| `06_teacher_approvals.png` | 教师审批中心 |
| `08_student_after_approval.png` | 审批后学生端状态同步 |
| `09_counselor_classes.png` | 辅导员负责班级 |
| `11_admin_home.png` | 管理控制台总览 |
| `13_admin_settings.png` | 系统配置与权限治理 |
| `14_student_notices.png` | 学生端看到管理员发布的公告 |

### 7.2 回归

回归在新增产品层之后执行（产品层不修改任何既有模块的代码）。

```powershell
python scripts/r10_full_regression.py --json
```

结果见 `.local/evidence/product/regression.log`；本轮改动为**纯新增**
（`smass_workspace/`、`settings_product.py`、`urls_product.py`、`static/workspace/`、
3 个脚本），未触碰既有业务代码。

---

## 8. 复现命令

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
cd E:\PythonWeb\smass\.local\clean-dev

# 1) 初始化隔离库与合成数据（可重复执行）
& $py scripts\product_bootstrap.py

# 2) 启动产品
& $py manage.py runserver 127.0.0.1:8050 --settings=smass.settings_product

# 3) 三端冒烟 / 浏览器验收
& $py scripts\product_smoke.py
& $py scripts\product_e2e.py --base http://127.0.0.1:8050

# 4) 历史迁移（预览 / 执行 / 校验 / 回滚）
& $py scripts\legacy_migration.py --preview
& $py scripts\legacy_migration.py --apply
& $py scripts\legacy_migration.py --verify
& $py scripts\legacy_migration.py --rollback
```

### 演示账号（合成数据）

| 账号 | 角色 | 落地 |
|---|---|---|
| `dev_admin` | 系统管理员 | `/admin/` |
| `dev_college` | 学院管理员（信息工程学院） | `/admin/` |
| `dev_teacher` | 教师（张明） | `/teacher/` |
| `dev_teacher2` | 教师（李华） | `/teacher/` |
| `dev_counselor` | 教师 + 辅导员（王芳） | `/teacher/`（含辅导员分组） |
| `dev_student` | 学生（陈晨） | `/student/` |
| `dev_student2/3/4` | 学生 | `/student/` |

口令由 `PRODUCT_DEV_PASSWORD` / `.env` 提供，仓库不保存明文。

---

## 9. 已知边界

1. 产品配置 `DEBUG=True`、`ALLOWED_HOSTS` 含 `*`，**仅限本机开发**，不可用于生产。
2. 排课种子数据是演示用 fixture，不是求解器输出；正式排课仍走 `/r11/plan/` 的
   确定性构造 + 回溯求解与独立复核。
3. 缴费为校内台账登记，**不接真实支付渠道**；退费需财务审批。
4. 历史迁移默认掩码 PII；真实原值迁移需数据所有者授权。
5. 教务深层操作（学年/课程/教学班/选课/流程定义编辑）仍使用既有功能页，
   通过统一导航进入，产品层未重写这些表单。
6. 学院管理员的数据范围以 `scope_college` 字符串匹配组织编码/名称；
   该字段为既有模型，未做数据库结构变更。

---

## 10. 变更清单

新增（未修改既有业务代码）：

```
smass/settings_product.py                 产品配置（隔离库 + 三端上下文）
smass/urls_product.py                     产品 URLConf
smass_workspace/                          产品层 app（导航/守卫/服务/视图/模板）
static/workspace/app.css                  统一设计系统
static/workspace/app.js                   统一交互脚本
scripts/product_bootstrap.py              隔离库 + 合成数据
scripts/product_smoke.py                  三端页面冒烟
scripts/product_e2e.py                    Chromium 浏览器验收
scripts/product_grant_check.py            授权生效验证
scripts/legacy_migration.py               app01 → 统一模型迁移/校验/回滚
```

保留：

- `smass/settings.py`、`smass/urls.py`、`app01/`、R4–R20 既有模块与测试
  **零改动**；旧入口按原路径可用。
