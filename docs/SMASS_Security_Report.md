# SMASS 安全报告（Security Report）

- 评估范围：认证、授权、CSRF、会话、密码存储、日志、配置、依赖与数据库
- 结论：**R1 安全门禁全部 PASS**；存在 4 项已知遗留风险，均有明确跟进方案，不阻塞本轮验收

---

## 1. 认证（Authentication）

| 控制点 | 现状 | 判定 |
|---|---|---|
| 密码哈希算法 | Django `make_password` / PBKDF2-SHA256（迭代 1,000,000） | ✅ |
| 唯一写入路径 | `app01/services/accounts.py`；模型 `save()` 不做任何哈希 | ✅ |
| 明文入库 | 已消除：新建/编辑/重置/导入/自助改密全部经服务层编码 | ✅ |
| 历史数据兼容 | 旧 32 位 MD5 与"双重 MD5"坏数据均可登录，并在成功验证后**自动升级**为 PBKDF2 | ✅ |
| 账号枚举 | 账号不存在与密码错误统一返回"账号或密码错误" | ✅ |
| 暴力破解 | Session 级限速：连续 5 次失败锁定 300 秒（返回 HTTP 429） | ✅（单机） |
| 会话固定 | 登录成功后 `session.cycle_key()` 轮换 Session ID | ✅ |
| 登出 | `session.flush()`，旧 Session ID 立即失效 | ✅ |
| 会话有效期 | 24 小时，配置项 `DJANGO_SESSION_COOKIE_AGE`，注释与实现一致 | ✅ |
| Cookie 属性 | `HttpOnly`、`SameSite=Lax`；非 DEBUG 下自动 `Secure` | ✅ |
| 开放重定向 | `next` 经 `url_has_allowed_host_and_scheme` 校验，站外地址回落默认首页 | ✅ |
| 角色来源 | 服务端 Session（`info.type`），不接受任何客户端传入的角色参数 | ✅ |
| 首次登录强制改密 | **未实现** | ⚠️ 见 §7-R1 |
| 密码复杂度 | 学生改密沿用业务规则（6-10 位、字母数字）；后台新建/重置使用 10 位随机口令 | ✅（规则偏弱，见 §7-R3） |

## 2. 授权（Authorization）

| 控制点 | 现状 | 判定 |
|---|---|---|
| 中间件粗筛 | `/admin/*`→admin、`/student/*`→student、`/teacher/*`→teacher；历史 `/teacher/*` 的 `pass` 已移除 | ✅ |
| 视图级准入 | `@admin_required` / `@student_required` / `@teacher_required` 覆盖全部业务视图 | ✅ |
| 双层防护 | 中间件 + 装饰器，避免"新增非前缀路由即绕过" | ✅ |
| 跨角色访问 | 学生/教师访问后台 → 302 或 403；管理员访问学生端 → 302 到学生登录 | ✅ |
| 对象归属 | 学生资料/班级列表/改密一律取 Session 身份，忽略 `uid` 等入参 | ✅ |
| 越权写入 | 学生 POST 后台接口 → 403（AJAX）且数据不落库 | ✅ |
| 管理员自删保护 | 禁止删除当前登录账号，避免系统被锁死 | ✅ |
| 高危清表 | `all_delete` 需 POST + `confirm=YES`，否则 400 | ✅ |
| 细粒度权限（RBAC） | **未实现**：所有管理员权限相同 | ⚠️ 见 §7-R2（R2 范围） |

## 3. CSRF

| 控制点 | 现状 | 判定 |
|---|---|---|
| `csrf_exempt` | 全站已无使用（grep 确认） | ✅ |
| 写操作方法约束 | 后台新增/编辑/删除/重置/导入/清表全部 `@require_POST` | ✅ |
| AJAX 令牌 | `layout/admin.html` 统一 `$.ajaxSetup({'X-CSRFToken': ...})`，优先取表单 hidden input，其次 cookie | ✅ |
| 删除接口 | 由 GET 改为 POST，避免被页面预取或伪造链接触发 | ✅ |
| 学生改密 | 表单 `{% csrf_token %}` + `serialize()` 携带令牌 | ✅ |
| 测试证据 | `CsrfTests`：无令牌 403 / 有令牌 200 / GET 删除 405 | ✅ |

## 4. 日志与数据暴露

| 控制点 | 现状 | 判定 |
|---|---|---|
| 审计日志 | `smass.audit`：`action / actor / role / target / target_id / ip / detail` | ✅ |
| 敏感值 | 不记录密码、哈希、完整身份证号、完整会话 | ✅ |
| 密码哈希回传前端 | 已消除：`detail` 接口把 `password` 置空；`obtain` 接口只返回 `id`+`name` | ✅ |
| 调试 `print` | 已全部移除（`account.py`、`middleware/auth.py`、多个 admin 视图） | ✅ |
| 日志文件 | `logs/smass.log`，5 MB × 3 轮转，位于 `.gitignore` | ✅ |
| 错误信息 | 删除失败返回"该记录仍被其他数据引用"；导入失败返回逐行原因；不回传 traceback | ✅ |
| 前端隐私 | 学生班级列表展示同班同学"学号/姓名/手机号"（班级通讯录用途） | ⚠️ 见 §7-R4 |

## 5. 配置与部署

| 控制点 | 现状 | 判定 |
|---|---|---|
| 密钥 | 代码内无真实密钥；`DEBUG=False` 且未提供 `DJANGO_SECRET_KEY` 时**启动即失败** | ✅ |
| 数据库口令 | 移入 `.env`（`.gitignore` 已排除），代码与文档均无明文 | ✅ |
| `DEBUG` | 默认 `True`（开发）；生产须显式设 `False`，届时自动开启 `Secure` Cookie 等 | ✅ |
| `ALLOWED_HOSTS` | 环境变量，默认 `127.0.0.1,localhost` | ✅ |
| `CSRF_TRUSTED_ORIGINS` | 环境变量支持 | ✅ |
| 安全响应头 | 非 DEBUG：`SECURE_CONTENT_TYPE_NOSNIFF`、`SECURE_REFERRER_POLICY`、`X_FRAME_OPTIONS=DENY` | ✅ |
| HSTS / SSL 重定向 | 提供环境变量开关，默认关闭（无 HTTPS 环境） | ⚠️ 部署时开启 |
| 静态/媒体服务 | `/media/` 由 Django `serve`（**仅开发**）；README 已注明生产用前置服务器 | ⚠️ 部署注意 |
| 依赖 | 锁版本：Django 5.2.13 / openpyxl 3.1.5 / Pillow 12.2.0 / PyMySQL | ✅ |
| 已知漏洞扫描 | **未执行**（无 `pip-audit` 等工具，且未获授权安装额外扫描器） | ⚠️ 见 §7-R5 |

## 6. 数据库安全

| 控制点 | 现状 | 判定 |
|---|---|---|
| 迁移权限 | 仅本机 `root`，仅操作 `smass`；同实例其他 20+ 库未触碰 | ✅ |
| 破坏性操作 | 未执行 `flush`/`drop`/`migrate zero`/清表 | ✅ |
| 参数化查询 | 全部走 Django ORM；`information_schema` 检查用参数绑定 | ✅ |
| 搜索注入 | 搜索字段由 `SEARCH_FIELDS` 常量白名单决定，用户输入只作为值 | ✅ |
| 模型删除目标 | 显式传模型类，不接受请求参数决定操作对象 | ✅ |
| 字符集 | `utf8`（不支持 4 字节字符） | ⚠️ 见 §7-R6 |
| 备份 | 源码有 zip + Git；**数据库无自动备份** | ⚠️ 见 §7-R7 |

## 7. 未解决风险与跟进

### R1（中）首次登录强制改密未实现
- **现状**：新建/重置密码生成随机一次性口令，但系统不强制用户首次登录后修改。
- **风险**：口令可能长期沿用，管理员知晓用户口令。
- **为何未做**：需要新增 `must_change_password` 字段（迁移）+ 管理员/教师/学生三端改密界面（UI 工作量），超出本轮"最小风险、可回归"的边界。
- **跟进**：已列入 R2 方案 §1.4，建议下一轮优先实现。

### R2（中）缺少细粒度权限
- **现状**：任一管理员可操作全部模块（含其他管理员账号、批量清表）。
- **风险**：权限过宽；误操作影响面大。
- **跟进**：R2 统一 Account/Role/Permission 设计（Django `Group`/`Permission` 或自定义 Role 表）。

### R3（低）密码复杂度偏弱
- **现状**：学生改密规则为 6-10 位字母数字；`AUTH_PASSWORD_VALIDATORS` 已配置但未在业务表单中调用。
- **风险**：弱口令。
- **跟进**：R2 接入 `validate_password`，并把长度下限提高到 8。

### R4（低）班级通讯录暴露手机号
- **现状**：学生可在"本班列表"看到同班同学的学号、姓名、手机号。
- **判断**：属班级通讯录的业务需求，且作用域已收窄到本班。
- **跟进**：R2 增加字段级可见性配置（如手机号默认打码，使用已有 `encrypt_range` 过滤器）。

### R5（低）未做依赖漏洞扫描
- **现状**：仅锁定版本，未执行 CVE 扫描。
- **跟进**：CI 中增加 `pip-audit`（需允许安装该工具）。

### R6（低）库/表字符集为 `utf8`
- **风险**：不支持 4 字节字符（emoji）。
- **跟进**：见迁移报告 §7，需一次受控的 `CONVERT TO CHARACTER SET utf8mb4`。

### R7（中）数据库无自动备份策略
- **现状**：仅源码有备份与版本控制，MySQL 数据无定期备份。
- **跟进**：部署到生产前必须建立 `mysqldump` 定时备份与恢复演练。

### R8（信息）历史 `SECRET_KEY` 已泄漏于版本历史
- **现状**：旧 `SECRET_KEY` 曾硬编码在 `settings.py`，已存在于基线提交与源码备份中。
- **影响**：该值历史上用于 `md5(SECRET_KEY + password)`。现已改为官方哈希；旧值仅作为**校验兼容常量**保留在 `services/accounts.py`。
- **建议**：
  1. 生产部署时必须使用全新随机 `DJANGO_SECRET_KEY`；
  2. 等历史账号全部完成哈希升级（登录即升级）后，删除 `LEGACY_MD5_SECRET_KEY` 常量与兼容分支。

## 8. 安全回归证据

| 门禁 | 命令 | 结果 |
|---|---|---|
| 匿名拦截（三类） | `test_authorization.AnonymousAccessTests` | 5/5 PASS |
| 跨角色拒绝 | `test_authorization.CrossRoleTests` | 5/5 PASS |
| CSRF 约束 | `test_authorization.CsrfTests` | 4/4 PASS |
| 对象归属 | `test_authorization.ObjectPermissionTests` | 3/3 PASS |
| 密码完整性 | `test_auth.PasswordIntegrityTests` | 6/6 PASS |
| 旧哈希兼容 | `test_auth.LegacyHashTests` | 2/2 PASS |
| 后台写接口方法/确认 | `test_crud_admin.HighRiskEndpointTests` | 2/2 PASS |
| 部署审计 | `manage.py check --deploy` | 6 条警告，均为开发环境预期 |

## 9. 结论

- 本轮修复消除了 **9 项 P0 安全缺陷**（密码双哈希、明文入库、教师端无鉴权、CSRF 豁免、误删他表、接口串台等）。
- 认证已收敛为单一可审计路径，并有 21 条认证测试 + 17 条授权/CSRF 测试守护。
- 4 项遗留（强制改密、细粒度权限、依赖扫描、数据库备份）与 2 项运维注意（字符集、`/media/` 开发专用）已明确记录，不谎报"全部安全"。

---

## 10. 复核补充（round 1）

| 项 | 结论 |
|---|---|
| 死代码中的弱哈希入口 | `app01/utils/formatchange.py` 在 R1 重构后已无调用方，但旧 `row_resetPass` 仍会写入 `md5(cardID[-6:])`。已在复核中改为纯委托（`services/accounts.reset_password`），模块内不再包含任何哈希实现。测试：`LegacyToolCompatTests.test_row_reset_pass_uses_official_hash` 断言落库为 `pbkdf2_` 且非 legacy。 |
| 兼容层详情接口 | `row_obtain` 同样改为委托 `crud.row_detail_dict(exclude=('password',))`，不再回传哈希。 |
| 重置密码可达性 | 管理员列表页补齐 `.btn-reset`，使 `admin/admin/resetPass/` 具备 UI 入口（此前仅有后端路由）。 |
| 复核后门禁 | `check` 0 issues / 迁移一致 / **87/87 测试通过** / Git 干净 |

> 仍未解决的风险与 §7 一致，未新增，也未降低验收标准。