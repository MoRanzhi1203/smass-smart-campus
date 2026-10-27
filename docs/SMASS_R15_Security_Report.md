# SMASS R1.5 安全报告（Security Report）

- 范围：高危操作、密码、日志、隐私、依赖与配置
- 结论：R1.5 安全门禁 **PASS**；含 5 项如实标注的遗留/未运行项

## 1. 高危入口普查（B.1）

对全部路由、装饰器、模板按钮、管理命令做了只读扫描，结果如下：

| 入口 | 数量 | 原始保护 | 本轮处置 |
|---|---|---|---|
| HTTP 清表 `/admin/*/list/all_delete/` | 3（student/teacher/classes） | POST + `confirm=YES` | **改为默认拒绝**：一律 403 + 审计，不再执行任何删除 |
| 重置密码 `/admin/*/resetPass/` | 4（admin/student/teacher + 兼容层） | 登录 + POST | 保留；改为随机一次性口令；响应 `no-store` |
| 批量导入 `/admin/*/multi/` | 5 | 登录 + POST | 保留；整批原子校验；响应 `no-store` |
| 重置前查询 `/admin/*/obtain/` | 2 | 登录 | 保留；响应 `no-store` |
| 受控清表命令 `purge_table` | 1（新增） | — | 三重门禁：白名单（**不含 Admin**）+ `--confirm` + `DEBUG`/`--allow-non-debug` |
| 删除单行 `/admin/*/delete/` | 8 | 登录 + POST + CSRF | 保留；禁止删除当前管理员 |

## 2. 清表默认拒绝（B.2）

计划要求"不因仅有 POST 和 confirm=YES 就视为充分授权"。实测：

```
POST /admin/student/list/all_delete/  {"confirm": "YES"}
→ 403  {"status": false, "error": "该操作已停用（HTTP 不提供批量清表）…purge_table…"}
→ 数据未发生任何删除
GET  /admin/student/list/all_delete/  → 405
```

审计日志记录 `action=dangerous_blocked`。

命令侧门禁（实测）：

| 场景 | 结果 |
|---|---|
| 无 `--confirm` | `CommandError` |
| `--model Admin` | `CommandError`（白名单外，避免锁死系统） |
| `--dry-run` | 只统计不删除 |
| `DEBUG=False` 且无 `--allow-non-debug` | `CommandError` |
| `DEBUG=False` + `--allow-non-debug` | 允许（显式授权） |

## 3. CSRF / 方法 / 角色（B.3 复验）

沿用 R1 的 17 条授权用例，本次全绿：

- 匿名访问三类受保护路径 → 302 或 403 JSON；
- 学生/教师越权 POST 后台 → 403 且**不落库**；
- 无 CSRF 令牌的 POST → 403；带令牌 → 200；
- GET 调删除接口 → 405；
- 管理员删除自己被拒。

## 4. 审计（B.4）

`smass.audit` 记录：`action / actor / role / target / target_id / ip / detail`。

- 失败场景**不落库**（事务回滚后无副作用），但审计行仍写入，便于排查；
- 新增 `dangerous_blocked`、`dangerous_purge`、`password_change`、`password_reset` 等动作；
- 不记录密码、哈希、完整身份证号、会话 ID。

## 5. 隐私最小披露（B.5）

| 场景 | 之前 | 现在 |
|---|---|---|
| 学生班级通讯录手机号 | 完整显示 `13987654321` | `139****4321`（`mask_phone`） |
| 模板过滤器空值 | `None` 会抛异常 | `mask_phone` / `mask_id_card` / `encrypt_range` 均空值安全、越界钳制 |

E2E 实测：页面出现 `139****4321`，**完整号码不出现**。

## 6. 历史 MD5 兼容（B.6）

保留 R1 的兼容行为，并新增**独立向量交叉验证**（不硬编码真实口令）：

- `legacy_md5(plain)` 与 `hashlib.md5(SECRET_KEY + plain)` 独立重算一致；
- 双重哈希向量同样一致；
- 官方哈希 `is_legacy_hash=False` / `is_preferred_hash=True`。

**如实说明**：无法证明"所有未知历史双重哈希都能恢复"。已知可恢复的是：
`md5(SECRET_KEY+plain)` 与 `md5(SECRET_KEY + md5(SECRET_KEY+plain))` 两种形态；
其他未知形态（例如旧密钥已变更、加了别的盐）不在保证范围内。

## 7. 一次性口令泄露面（B.7）

| 面 | 处置 |
|---|---|
| 浏览器缓存/代理缓存 | 新增 `SensitiveResponseMiddleware`：`/resetPass/`、`/multi/`、`/obtain/` 统一 `Cache-Control: no-store, no-cache, must-revalidate, private, max-age=0` + `Pragma: no-cache` + `X-Robots-Tag: noindex` |
| 日志 | 口令明文不写日志；审计只记录"发生过重置" |
| 异常响应 | 口令只在成功 JSON/渲染页中出现；失败走统一错误消息 |
| 浏览器历史/回退 | `no-store` 可阻止从缓存恢复；但**用户若手工复制/截图无法防护**（属使用侧风险） |
| 页面标题/URL | 口令不出现在 URL 或 title |

普通列表页**不加** `no-store`（避免误伤缓存），实测验证。

## 8. 依赖与配置（R1.5-D）

| 项 | 结果 |
|---|---|
| `requirements.txt` 一致性 | **修正**：原写 `PyMySQL==1.1.2`，实测 conda 环境解析到 **1.4.6**；改为 `>=1.1.2,<2` 并注明 |
| `environment.yml` | 与 requirements 同步（python 3.12 / Django 5.2.13 / openpyxl / Pillow / PyMySQL） |
| PyMySQL 版本 shim | **改为条件生效**：仅当 `version_info < (1,4,3)` 时才声明兼容版本；**不覆盖** `pymysql.__version__`（实测仍读到真实 `1.4.6`，说明 shim 未触发） |
| 保守替代 | 安装 `mysqlclient` 后可完全删除 shim（需 MSVC 工具链），已写入 `requirements.txt` 注释 |
| `validate_password` 接入 | **已接入**：后台账号自填密码经 `BaseAccountModelForm.clean_password`，学生改密在业务规则后叠加；`MinimumLengthValidator` 的 `min_length` 调整为 6 以兼容既有业务规则（6-10 位字母数字） |
| 密码规则 | 未缩短允许字符集，未截断口令 |
| `check --deploy` | 6 条警告（W004/008/009/012/016/018），均为开发环境预期；`DEBUG=False` 时 `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` 自动开启 |

## 9. 部署检查表（摘录）

| 项 | 要求 |
|---|---|
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | 全新随机值（代码在 DEBUG=False 且缺失时**拒绝启动**） |
| `DJANGO_ALLOWED_HOSTS` | 真实域名，禁止留空 |
| HTTPS | 前置服务器启用；`DJANGO_SECURE_SSL_REDIRECT=True` |
| HSTS | `DJANGO_SECURE_HSTS_SECONDS` > 0（确认全站 HTTPS 后） |
| `/media/` | 由前置服务器托管，不用 Django `serve` |
| 数据库 | 专用低权限账号（非 root）；开启每日备份 |
| 字符集 | 按 `scripts/charset_drill.ps1` 的方案转 `utf8mb4` |
| 日志 | `logs/smass.log` 轮转；确保不含敏感值 |

## 10. 未解决 / 未运行（如实）

| 项 | 状态 | 说明 |
|---|---|---|
| 依赖漏洞扫描（`pip-audit` 等） | **NOT RUN** | 工具未安装，本轮未获授权安装第三方扫描器。**明确未做，不虚报** |
| 首次登录强制改密（三端 UI） | **NOT DONE** | 与 R2.0 身份迁移冲突；只在原型 `Account` 加字段并设计 |
| 持久化登录限速运行逻辑 | **原型字段已建，逻辑未接** | 当前仍为 Session 级限速（5 次/300 秒） |
| 库/表字符集 | 仍为 `utf8` | 已产出可复跑的转换演练方案（24 FK 重建验证），**未对正式库执行** |
| 数据库自动备份 | **待部署** | 脚本与冒烟就绪，计划任务需授权 |
| 历史 `SECRET_KEY` 泄漏于版本历史 | 已知风险 | 已改为仅用于 legacy 校验常量；生产须换新密钥 |
| 细粒度 RBAC | 未上线 | 本轮只做隔离原型与 ADR |

## 11. 结论

- 高危批量销毁已从"HTTP 可触发"降级为"默认拒绝 + 受控命令"；
- 一次性口令的缓存面已封堵，并有测试守护；
- 学生侧个人信息默认最小披露；
- 密码写入路径仍保持唯一（`services/accounts`），并叠加了官方强度校验；
- 未运行项已逐条标注，未做虚假"ALL PASS"。
