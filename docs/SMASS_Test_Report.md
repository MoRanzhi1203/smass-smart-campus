# SMASS 测试报告（Test Report）

- 执行时间：2026-10-27
- 执行环境：Windows / conda env `smass` / Python 3.12.16 / Django 5.2.13 / MySQL 8.0.18
- 测试数据库：`test_smass`（Django 自动创建与销毁，**不触碰开发库 `smass`**）
- 总耗时：约 81 秒（全量）

## 1. 执行命令

```powershell
# 全量测试
conda run -n smass python manage.py test app01 -v 1

# 一键门禁（check + 迁移一致性 + 测试 + deploy 审计）
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

## 2. 结果总览

| 指标 | 值 |
|---|---|
| 用例总数 | **87** |
| 通过 | **87** |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | 0 |
| 最终状态 | **OK** |

| 门禁项 | 命令 | 结果 |
|---|---|---|
| Django 系统检查 | `manage.py check` | **PASS**（0 issues） |
| 迁移一致性 | `manage.py makemigrations --check --dry-run` | **PASS**（No changes detected） |
| 单元/集成测试 | `manage.py test app01` | **PASS**（87/87） |
| 部署风险审计 | `manage.py check --deploy` | **WARN 6 条**（开发环境预期，非门禁） |

### 2.1 部署审计的 6 条警告（明确属开发环境预期）

| 编号 | 内容 | 处理 |
|---|---|---|
| W004 | 未设置 `SECURE_HSTS_SECONDS` | 生产部署前按 HTTPS 策略设置 |
| W008 | `SECURE_SSL_REDIRECT` 未开启 | 生产用前置服务器或开启该项 |
| W009 | `SECRET_KEY` 为开发占位值（`django-insecure-` 前缀） | 生产必须注入 `DJANGO_SECRET_KEY`（代码已强制） |
| W012 | `SESSION_COOKIE_SECURE` 未开启 | `DEBUG=False` 时代码已自动开启 |
| W016 | `CSRF_COOKIE_SECURE` 未开启 | 同上 |
| W018 | `DEBUG=True` | 生产设 `DJANGO_DEBUG=False` |

> 说明：W012/W016 在 `DEBUG=False` 下由 `settings.py` 自动设为 `True`，届时警告自然消失。

## 3. 用例分布

| 文件 | 测试类 | 用例数 | 覆盖点 |
|---|---|---|---|
| `text_auth.py`（认证） | `LoginTests` | 10 | 三角色登录、错误密码、身份表隔离、会话轮换、登出失效、开放重定向、失败锁定 |
| | `PasswordIntegrityTests` | 6 | 编辑不改密码、编辑改密码、新建随机密码、明文禁入库、管理员/学生重置 |
| | `StudentChangePasswordTests` | 3 | 改密成功、原密码错误、GET 拒绝 |
| | `LegacyHashTests` | 2 | 旧 MD5 登录并升级、双重哈希坏数据修复 |
| `test_authorization.py`（授权） | `AnonymousAccessTests` | 5 | 三类页面匿名拦截、公开页、AJAX 403 |
| | `CrossRoleTests` | 5 | 学生↔管理员↔教师交叉拒绝、越权写入被拒 |
| | `CsrfTests` | 4 | 无令牌 403、有令牌通过、GET 删除 405、禁止自删 |
| | `ObjectPermissionTests` | 3 | profile 只见自己、班级列表限本班、改密忽略传入 uid |
| `test_crud_admin.py`（CRUD） | `ListAndSearchTests` | 6 | 9 列表渲染、9 列表搜索、关键词回显、非法页码、部门真实字段 |
| | `CrossModuleIsolationTests` | 5 | 班委/团干 endpoints 正确、删除不波及部门、详情无密码 |
| | `ModelLogicTests` | 2 | `connect_instructors` 修正与"不覆盖已分配" |
| | `CrudRoundTripTests` | 9 | 9 个模块 增-查-改-删 往返 |
| | `HighRiskEndpointTests` | 2 | `all_delete` 需 POST + `confirm=YES` |
| `test_imports.py`（导入） | `TemplateConsistencyTests` | 3 | 模板表头与解析器一致（学生/教师/班级） |
| | `StudentImportTests` | 6 | 哈希口令、重复跳过、非法外键整批回滚、非法性别、非 Excel、缺文件 |
| | `TeacherImportTests` | 3 | 职务中间表创建、未知职务/院系回滚 |
| | `OrgImportTests` | 5 | 学院幂等、专业校验、班级往返与回滚 |
| `test_compat_tools.py`（兼容层/UI） | `LegacyToolCompatTests` | 5 | 兼容层不再写 MD5、删除绑定目标模型、详情屏蔽密码 |
| | `AdminListUiTests` | 3 | 管理员页重置按钮与端点、无无效导入入口 |
| **合计** | | **87** | |

## 4. 首轮失败与修复记录（真实过程）

首轮执行：`Ran 87 tests`，**4 FAIL + 1 ERROR**。逐项定位：

| 失败用例 | 报错摘要 | 根因 | 修复 |
|---|---|---|---|
| `test_edit_profile_without_password_keeps_hash` | `'' != 'pbkdf2_sha256$...'` | `password` 在 `Meta.fields` 中，`ModelForm._post_clean()` 用 `construct_instance` 把空值写回 `instance.password` | 把 `password` 改为**非模型字段**（不列入 `Meta.fields`） |
| `test_admin_cannot_delete_self` | `Content-Type is "text/html"` | 测试用了未登录的 `self.client`，被中间件 302 | 改用已登录且带 CSRF 令牌的 `csrf_client` |
| `test_student_roundtrip` | `pinyin/building/dormitory 必填` | 字段 `null=True` 但无 `blank=True` | 表单层 `optional_model_fields` 设 `required=False` |
| `test_teacher_roundtrip` | `pinyin 必填` | 同上 | 同上 |
| `test_connect_instructors_uses_counsellor_field` | `None != 'T000010'` | 实现硬编码 `position_id=1`，测试中自增 id 非 1 | 改按 `position__name='辅导员'` 匹配 |

第二轮：`Ran 87 tests ... OK`（0 失败）。

> 这说明测试确实在验证行为而非"为通过而写"。特别是第 1 项：**修复过程中新引入的缺陷被测试立即捕获**，
> 也印证了"同一类 bug 会以不同形式复发"的判断。

## 5. 覆盖矩阵（对照计划 §9）

| 计划要求 | 覆盖情况 | 证据 |
|---|---|---|
| 9.1 基础与环境（check / makemigrations / showmigrations / migrate --plan / 实际迁移） | 全部执行 | 见 `SMASS_Migration_Report.md` |
| 9.1 `check --deploy` | 已执行，6 条预期警告 | 本报告 §2.1 |
| 9.2 三角色正确/错误登录 | 覆盖 | `LoginTests` |
| 9.2 编辑资料后原密码有效、哈希未变 | 覆盖 | `test_edit_profile_without_password_keeps_hash` |
| 9.2 改密/重置后新密码有效、旧密码失效 | 覆盖 | `StudentChangePasswordTests`、`PasswordIntegrityTests` |
| 9.2 导入不出现明文密码 | 覆盖 | `test_import_success_uses_hashed_password` |
| 9.2 登出/会话策略 | 覆盖 | `test_logout_invalidates_session`、`test_session_key_rotated_on_login` |
| 9.3 匿名访问三类页面被拒 | 覆盖 | `AnonymousAccessTests` |
| 9.3 跨角色拒绝 | 覆盖 | `CrossRoleTests` |
| 9.3 学生不能改他人资料 | 覆盖 | `ObjectPermissionTests` |
| 9.3 CSRF 缺失拒绝 / 合法通过 | 覆盖 | `CsrfTests` |
| 9.4 九模块 CRUD + 搜索 + 分页 | 覆盖 | `test_crud_admin.py` |
| 9.4 班委不串台、不误删部门 | 覆盖 | `CrossModuleIsolationTests` |
| 9.4 重置密码路由正确、不依赖 cardID | 覆盖 | `test_admin_reset_password_returns_working_password` |
| 9.4 导入各类异常有可解释结果 | 覆盖 | `test_imports.py` |
| 9.4 测试数据隔离、自动清理 | 覆盖 | 使用 `test_smass`，Case 事务回滚 |

## 6. 未覆盖 / 局限（如实声明）

1. **浏览器端 JS 行为**（模态框、`X-CSRFToken` 注入、`endpoints` 取值）未做端到端测试；
   仅通过"模板渲染成功 + 服务端接口按 POST/CSRF 契约工作"间接保证。
2. **并发与性能**未测（无查询数基准）。`select_related` 已用于列表页，但未做 N+1 计数基准。
3. **编码边界**：未专门测试 emoji/四字节字符（库字符集为 `utf8`，见迁移报告）。
4. **邮件/短信/外部服务**：项目本无此类依赖，未覆盖。
5. **`NicePagination`（学生端 BS5 分页）**仅有渲染级验证（学生页面 200），未做页码边界单测。
6. **浏览器兼容性**（Bootstrap 3/5 混用）未测，属 R2 UI 统一范围。

## 7. 结论

- 计划 §9 中所有可自动化的门禁均已落地并 **PASS**。
- 87 个用例覆盖了认证、授权、CSRF、9 模块 CRUD、批量导入、迁移与种子数据。
- 无"预计通过"占位：所有结论来自实际执行输出。
