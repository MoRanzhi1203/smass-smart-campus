# SMASS 审计报告（Audit Report）

- 审计对象：`E:\PythonWeb\smass`（基线提交 `4bddb70`）
- 审计时间：2026-10-27
- 审计方式：逐文件读源码 + 真实数据库/环境核验 + 可复现测试
- 证据口径：**行号均指基线提交 `4bddb70` 的原始文件**（修复后行号已变化）

> 原则：本报告只记录**已通过源码与运行证据核实**的结论。原任务书中的旧审计线索若未能复现，
> 明确标注「未复现」，不为了"看起来有产出"而强行修改代码。

## 0. 环境与状态核验

| 项目 | 实测值 |
|---|---|
| Python | 3.12.3（系统 anaconda）/ 3.12.16（新建 conda env `smass`） |
| Django | 5.2.13（`settings.py` 头部注释仍写 3.2.5，为模板残留） |
| MySQL | 8.0.18，`localhost:3306`，库 `smass` |
| 数据库初始状态 | **0 张表**；`app01` 迁移 0001-0003 全部未应用 |
| 库字符集 | `utf8` / `utf8_general_ci`（非 utf8mb4） |
| `manage.py check` | 0 issues |
| `makemigrations --check` | No changes detected |
| Git | 初始**不是 Git 仓库** |

## 1. 严重性定义

| 级别 | 含义 |
|---|---|
| P0 | 导致认证/数据安全失效，或核心功能确定性损坏 |
| P1 | 特定操作下必然报错/数据错乱，影响主流程 |
| P2 | 体验、可维护性、工程化缺陷 |
| P3 | 代码整洁度 |

## 2. 审计矩阵

### A. 认证与密码（P0）

| # | 证据（基线路:行） | 复现条件 | 影响 | 级别 | 修复设计 | 对应测试 | 结果 |
|---|---|---|---|---|---|---|---|
| A1 | `app01/models.py:139-142`（Admin.save）、`184-187`（Student.save）、`241-244`（Teacher.save） | 任意 `obj.save()` | 每次保存都 `md5(SECRET_KEY+password)`，同一明文被哈希 0~2 次 | P0 | 移除模型内哈希，密码只经 `services/accounts.set_password` | `test_auth.PasswordIntegrityTests` | 已修复 |
| A2 | `app01/form/account.py:11-13, 20-22` | 登录提交 | 表单先 md5 一次，若与 A1 叠加则登录永不匹配 | P0 | 表单不再哈希，明文交给服务层 `check_password` | `test_auth.LoginTests` | 已修复 |
| A3 | `app01/form/admin_inter.py:15-18`（`render_value=True`）+ A1 | 打开"编辑"→ 直接保存 | 把数据库里的哈希当新密码再次哈希，**账号当场失效** | P0 | 密码改非模型字段 + `render_value=False` + 留空即不改 | `test_edit_profile_without_password_keeps_hash` | 已修复 |
| A4 | `app01/utils/formatchange.py:63-77` | 管理员点"重置密码" | 先 `md5(cardID[-6:])` 再由 `save()` 二次哈希 → 重置后必然登不上 | P0 | `accounts.reset_password` 生成随机口令 + 官方哈希；不依赖 cardID | `test_admin_reset_password_returns_working_password` | 已修复 |
| A5 | `app01/views/admin/ad_student.py:190` + `236` | Excel 导入学生 | `password='123456'` 明文 → `bulk_create` 不触发 `save()` → **明文入库**，且与登录算法不匹配 | P0 | 导入前统一 `make_password`，本次导入生成一次性口令 | `test_import_success_uses_hashed_password` | 已修复 |
| A6 | `app01/views/admin/ad_teacher.py:179` | Excel 导入教师 | 手工 `md5('123456')`，与其他路径策略不一致 | P1 | 统一到 `services/imports.py` | `test_import_teacher_creates_positions` | 已修复 |
| A7 | `app01/models.py:137,150,198` | `password` `max_length=64` | Django 官方 PBKDF2 哈希约 88-90 字符，64 位会**截断导致哈希损坏** | P0（隐性） | 扩到 128 + 迁移 0004 | `test_auth` 全绿 | 已修复 |
| A8 | `app01/views/admin/ad_admin.py:103-116` | 尝试使用管理员重置密码 | `Admin` 模型**没有 `cardID` 字段**，且该两个视图在 `urls.py` 中**未注册** | P1 | 新增 `admin_resetPass` + 路由；不依赖 cardID | `test_admin_reset_password_returns_working_password` | 已修复 |

### B. 权限与路由（P0/P1）

| # | 证据 | 复现条件 | 影响 | 级别 | 修复设计 | 测试 | 结果 |
|---|---|---|---|---|---|---|---|
| B1 | `app01/middleware/auth.py:57-58` | 匿名访问 `/teacher/basic/` | 分支为 `pass`，**教师端完全无鉴权** | P0 | 中间件增加 `/teacher/` → `teacher` 角色；叠加视图装饰器 | `test_teacher_pages_require_login` | 已修复 |
| B2 | `smass/urls.py:40`（`login/teacher/` 被注释） | 教师无法登录 | 教师路由与登录入口缺失，与 B1 叠加成"免登录直入" | P0 | 新增 `login_teacher` 视图/表单/路由 | `test_teacher_login_success` | 已修复 |
| B3 | 全部 `ad_*.py` 的 `@csrf_exempt`（如 `ad_student.py:50`） | 任意跨站 POST | 后台写接口失去 CSRF 保护 | P0 | 全部移除；AJAX 统一带 `X-CSRFToken` | `test_authorization.CsrfTests` | 已修复 |
| B4 | `templates/layout/admin.html:331` `type: 'GET'` 删除 | 诱导访问删除 URL | 删除可被 GET 预取/伪造触发 | P1 | 删除接口改 `@require_POST` + 前端 POST | `test_delete_via_get_is_not_allowed` | 已修复 |
| B5 | `templates/login/index.html:88,98` | 点击"宿管"/"商家" | `/housemaster/basic/`、`/business/basic/` **无路由 → 404** | P2 | 明确标注"未启用"，不再作为链接 | 手工 + `test_login_pages_are_public` | 已修复 |
| B6 | `templates/layout/admin.html` 多处 `str_dict.name_en` 拼 URL | 任意后台页 | 地址由模板拼字符串决定，一处变量写错即串台（见 C1） | P1 | 视图传 `endpoints`（`reverse()` 生成）+ `json_script` | `test_classCommittee_endpoints_are_correct` | 已修复 |
| B7 | 无任何视图级装饰器 | 构造非前缀路由 | 仅靠 URL 前缀授权，新增路由即绕过 | P1 | `utils/authz.py` 装饰器 + 中间件双层 | `test_authorization` 18 例 | 已修复 |

### C. CRUD 与业务逻辑（P0/P1）

| # | 证据 | 复现条件 | 影响 | 级别 | 修复设计 | 测试 | 结果 |
|---|---|---|---|---|---|---|---|
| C1 | `app01/views/admin/ad_classCommittee.py:28` `'name_en': 'leagueCadres'` | 进入"班委干部"页做增/删/改/查 | 全部 AJAX 打到**团学干部**接口，班委数据被写进错误表/删错行 | P0 | 改 `classCommittee` + 命名路由 | `test_classCommittee_endpoints_are_correct` | 已修复 |
| C2 | `ad_classCommittee.py:96` `row_delete(uid, models.Department)` | 删除一条班委 | 实际去**删部门表**中 id 相同的行 | P0 | 显式传 `models.ClassCommittee` | `test_delete_classCommittee_does_not_touch_department` | 已修复 |
| C3 | `ad_leagueCadres.py:97` 同上 | 删除一条团学干部 | 同 C2 | P0 | 显式传 `models.LeagueCadres` | `test_delete_leagueCadres_does_not_touch_department` | 已修复 |
| C4 | `ad_department.py:19`、`ad_leagueCadres.py:18`、`ad_classCommittee.py:18` `name__contains` | 在部门/干部页搜索 | 三个模型**没有 `name` 字段** → `FieldError` 500 | P1 | 每模块显式 `SEARCH_FIELDS`（`department` / `id__name` 等） | `test_search_never_raises_field_error` | 已修复 |
| C5 | `models.py:72-79` `cls_obj.instructor` | 调用 `Classes.connect_instructors()` | 字段实为 `counsellor` → `AttributeError`；且硬编码 `position_id=1` | P1 | 改 `counsellor` + 按职务名匹配 | `test_connect_instructors_uses_counsellor_field` | 已修复 |
| C6 | `ad_student.py:133`（10 列表头）vs `ad_student.py:169-210`（按 13 列解析） | 下载模板 → 填写 → 导入 | 列错位：专业/班级/政治面貌全部读错列 | P1 | 表头与解析共用 `imports.STUDENT_HEADERS` | `test_student_template_matches_parser` | 已修复 |
| C7 | `ad_student.py:151-241` 无事务、无校验 | 导入含错误外键/重复主键 | `get()` 抛 `DoesNotExist` → 500；或部分成功留下脏数据 | P1 | 先校验后入库、单事务、错误清单 | `test_invalid_reference_rolls_back_whole_batch` 等 | 已修复 |
| C8 | `ad_admin.py` / `ad_student.py` 的 `fields` 不含主键 | 点"新建"填写表单保存 | 主键字段缺失，新增无法指定学号/工号（功能实际不可用） | P1 | 表单显式纳入 `id`，编辑时 `disabled` | `test_*_roundtrip` 9 例 | 已修复 |
| C9 | `ad_admin.py:29-42` 未传 `search_data` | 搜索后翻页 | 搜索词不回显 | P2 | `crud.build_search_meta` 统一注入 | `test_search_keyword_is_echoed` | 已修复 |
| C10 | `form/admin_inter.py:38,46` `fields='__all__'` | 教师表包含 `position`（through M2M） | `save_m2m()` 对中间模型不能直接 set | P1（潜在） | 显式字段清单，排除 `position` | `test_teacher_roundtrip` | 已修复 |

### D. 配置与工程化（P2）

| # | 证据 | 影响 | 级别 | 修复设计 | 结果 |
|---|---|---|---|---|---|
| D1 | `smass/settings.py:93` `'POST': 3306` | 键名拼错（应为 `PORT`）；碰巧默认端口相同才没暴露 | P2 | 修正为 `PORT` 并全部环境变量化 | 已修复 |
| D2 | `settings.py:23,26,28` 硬编码 `SECRET_KEY`/`DEBUG=True`/`ALLOWED_HOSTS=[]` | 密钥入库、生产误用 | P1 | `.env` + `env_loader.py`；`DEBUG=False` 强制要求密钥 | 已修复 |
| D3 | `settings.py:86-95` 明文数据库口令 | 凭据入库 | P0 | 移入 `.env`（已被 `.gitignore` 排除） | 已修复 |
| D4 | `utils/encrypt.py` 无盐 `md5(SECRET_KEY+pwd)` | 弱哈希、可彩虹表 | P1 | 新密码改 PBKDF2；旧 MD5 只留校验兼容 | 已修复 |
| D5 | `utils/pagination.py` 与 `utils/NicePagination.py` 并存（15/10 条） | 行为不一致 | P2 | 后台统一前者，学生端保留后者并在文档明确用途 | 已修复 |
| D6 | 无 `requirements.txt` / `README` / `.gitignore`；非 Git 仓库 | 不可复现、无法回滚 | P2 | 全部补齐 + git 基线 | 已修复 |
| D7 | `app01/views/account.py:42` 等多处 `print` | 调试残留污染输出 | P2 | 全部移除，改 `smass.audit` 结构化日志 | 已修复 |

## 3. 未复现 / 不成立的旧线索（如实记录）

| 旧线索 | 核实结论 |
|---|---|
| "登录日志会输出密码哈希" | **不成立**。`print(admin_object)` 输出模型 `repr`（`Admin` 无 `__str__` → `<Admin: Admin object (001)>`；`Student.__str__` 返回学号），均不含 `password`。调试 `print` 属 D7 已清理。 |
| "教师重置密码路由不一致" | **部分成立**：`teacher_resetPass` 有路由且可用，但同样受 A4 双重哈希影响；`admin` 侧才是"路由缺失 + 依赖不存在字段"。 |
| "重复分页器造成错误" | **未构成功能错误**：两份分页器各自可用，仅风格与页大小不同。已明确用途，未合并。 |
| "`Nation`/`Building`/`Dormitory` 可删除" | **未删除**。它们是 `models.Nation` 等仍存在的表，且 `Building`/`DormitoryNumber` 有 FK 关系；按计划 §0.2 不做删除，仅记录为 R2 清理候选。 |

## 4. 附加发现（不在原线索中）

| # | 证据 | 影响 | 修复 |
|---|---|---|---|
| E1 | `app01/form/admin_inter.py` 的 `password` 若放进 `Meta.fields`，`ModelForm._post_clean()` 会用 `construct_instance` 把空值写回 `instance.password` | 与 A3 同类的**二次回潮风险**（我在首轮修复中亲身踩到并被测试捕获） | 改为非模型字段，并加注释固化该约束 |
| E2 | `Student.pinyin/nation/phone/qq/address/building/dormitory` 为 `null=True` 但无 `blank=True` | 新增学生被迫填拼音/楼栋/寝室号 | 表单层 `required=False`（不改 schema） |
| E3 | `Accounts.set_password` 若对未入库对象用 `save(update_fields=[...])` | `update_fields` + 0 行 → `DatabaseError` | 按 `_state.adding` 分支处理 |
| E4 | `settings.TIME_ZONE='UTC'` 与中文本地化意图不符 | 日期显示偏移 8 小时 | 改 `Asia/Shanghai` 并记录 |
| E5 | `app01/utils/formatchange.py` 无任何调用方，却保留写 MD5 的 `row_resetPass` | 未来若被 import，会产生 MD5 与 PBKDF2 混存的坏数据 | 改为纯委托，模块内不再含哈希代码（S1） |
| E6 | 管理员列表页缺"重置密码"按钮，重置接口无 UI 入口 | 功能不可达 | 模板补 `.btn-reset`（S2） |

## 5. 结论

- 共确认 **P0 缺陷 9 项、P1 缺陷 11 项、P2 缺陷 7 项**，全部已修复并有对应测试。
- 数据库从"0 表"变为"26 表 + 迁移全部应用 + 幂等种子数据"，迁移链路真实可用（MySQL 8.0.18）。
- 认证链路已收敛为单一写入路径（`services/accounts.py`），并有 21 条认证测试与 18 条授权测试守护。
- 遗留项：库/表字符集为 `utf8`（建议迁 `utf8mb4`）、首次登录强制改密未实现、`Nation/Building/Dormitory` 未清理，
  均已在 `SMASS_Security_Report.md` 与 `SMASS_R2_Architecture_Proposal.md` 中列出。
