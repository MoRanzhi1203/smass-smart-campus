# SMASS R1.5–R2.0 变更清单（Change Log）

- 分支：`feat/smass-r15-r20-hardening`（基点 `d4caa88`）
- 规模：**43 files changed, +3416 / −424**（截至原型提交）
- 提交（不推送远程）：

| 提交 | 内容 |
|---|---|
| `d4caa88` | chore(r15)：纳入执行计划并建立分支 |
| `df4d537` | feat(r15-a)：数据库备份、隔离恢复演练、防误连 |
| `3780591` | feat(r15-b)：高危操作默认拒绝、受控清表、隐私脱敏 |
| `94a1a96` | feat(r15-cd-r20)：浏览器 E2E、依赖加固、统一账号隔离原型 |
| 收尾提交 | test(r15)：查询数基准 + 8 份交付文档 |

## 1. 新增文件

### 1.1 数据库保护（R1.5-A）

| 文件 | 作用 |
|---|---|
| `scripts/db_backup.ps1` | mysqldump 一致性备份；凭据走临时 defaults-extra-file |
| `scripts/db_restore_drill.ps1` | 隔离演练库创建/导入/校验/销毁，双重防误连 |
| `scripts/db_verify.py` | 只读一致性比对（表/行数/迁移/外键）+ `--check-target`/`--exists` |
| `scripts/db_backup_scheduled.ps1` | 定时备份包装 + 保留策略（不自行创建计划任务） |

### 1.2 高危与隐私（R1.5-B）

| 文件 | 作用 |
|---|---|
| `app01/management/commands/purge_table.py` | 受控清表命令：白名单（不含 Admin）+ `--confirm` + DEBUG 门禁 + `--dry-run` |
| `app01/middleware/privacy.py` | `/resetPass/` `/multi/` `/obtain/` 响应统一 `no-store` |
| `app01/tests/test_high_risk.py` | 22 例：清表拒绝、命令门禁、no-store、脱敏、MD5 向量 |

### 1.3 浏览器 E2E（R1.5-C）

| 文件 | 作用 |
|---|---|
| `tests_e2e/__init__.py` | 独立测试包（不进入 app01 常规门禁） |
| `tests_e2e/test_browser.py` | 16 例 Playwright 用例 |

### 1.4 字符集演练（R1.5-D）

| 文件 | 作用 |
|---|---|
| `scripts/charset_drill.ps1` | 隔离库 utf8mb4 转换（预生成 FK → DROP → CONVERT → 重建） |

### 1.5 R2.0 原型

| 文件 | 作用 |
|---|---|
| `proto_account/__init__.py` / `models.py` / `migrations/0001_initial.py` | Account / AccountRole / StudentProfile / TeacherProfile |
| `proto_account/management/commands/backfill_accounts.py` | 幂等回填（`--dry-run` / `--since` / `--rollback`） |
| `smass/settings_proto.py` | 原型专用配置（库名硬性隔离 + 追加 app） |
| `scripts/proto_verify.py` | 回填一致性校验（含密码原样性） |
| `scripts/proto_failure_injection.py` | 9 项失败注入 |

### 1.6 测试与账本

| 文件 | 作用 |
|---|---|
| `app01/tests/test_query_budget.py` | 查询数基准（本轮捕获并修复一个 N+1） |
| `docs/dsh_run/BASELINE_REPORT.md` | R0 工作基线 |
| `docs/dsh_run/archive_r1/*` | R1 轮账本归档（`git mv`，保留历史） |

## 2. 修改文件（关键）

| 文件 | 变更 | 兼容性 |
|---|---|---|
| `app01/views/admin/ad_student.py` | `all_delete` → 403 受控禁用；`select_related` 补 `classes__major__college` | HTTP 清表行为变化（见 §3） |
| `app01/views/admin/ad_teacher.py` | `all_delete` → 403 | 同上 |
| `app01/views/admin/ad_classes.py` | `all_delete` → 403 | 同上 |
| `app01/templatetags/custom_filters.py` | 新增 `mask_phone`/`mask_id_card`；`encrypt_range` 空值与越界安全 | 向后兼容 |
| `templates/student/classes-list.html` | 手机号改用 `mask_phone` | 学生侧显示变化 |
| `app01/form/admin_inter.py` | `clean_password` 接入 `validate_password` | 弱口令会被拒绝 |
| `app01/views/student/st_users_profile.py` | 改密叠加官方强度校验 | 弱口令会被拒绝 |
| `smass/settings.py` | `MinimumLengthValidator` `min_length=6`；中间件追加 `privacy` | 兼容既有 6-10 位规则 |
| `smass/__init__.py` | PyMySQL shim 改为条件生效，不覆盖真实 `__version__` | 行为更安全 |
| `requirements.txt` | `PyMySQL==1.1.2` → `>=1.1.2,<2`（实测 1.4.6） | 如实反映 |
| `app01/tests/test_crud_admin.py` | 清表断言 400 → 403 | 与实现同步 |

## 3. 用户可见行为变化

| 场景 | 之前 | 现在 |
|---|---|---|
| 通过浏览器清空学生/教师/班级表 | POST + `confirm=YES` 即执行 | **一律 403**，须用 `python manage.py purge_table --model X --confirm` |
| 学生班级通讯录手机号 | 完整显示 | `139****4321` |
| 后台设置弱口令 | 可能被接受 | 被 Django 校验器拒绝（含常见口令/纯数字） |
| 重置密码 / 导入结果页 | 可被缓存 | 响应带 `no-store` |
| 学生列表查询数 | 10（随行数线性增长） | **4**（恒定） |
| PyMySQL 版本 | 无条件伪造为 1.4.6 | 仅在低于阈值时声明兼容；真实版本可读 |

## 4. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 清表 HTTP 入口被禁用，若有外部脚本依赖会失效 | 响应中给出替代命令；仓库内无依赖 | `git revert` 对应提交 |
| 密码强度校验可能拒绝既有弱口令 | 仅在"设置新密码"时校验，登录不受影响 | 移除 `clean_password` 中的调用 |
| `no-store` 全局中间件可能影响性能 | 只匹配 3 个路径正则 | 从 `MIDDLEWARE` 移除一行 |
| 原型 app 被误加载进正式配置 | `settings.py` 不含 `proto_account`；`settings_proto` 有库名硬断言 | 删除 `proto_account/` |
| 原型库占用空间 | 独立库 `smass_proto_account` | `DROP DATABASE smass_proto_account` |
| 字符集演练脚本误连正式库 | 源码固定 `smass` 源 + `smass_proto_charset_*` 目标 | — |

## 5. 明确未做的变更

| 项 | 原因 |
|---|---|
| 修改 `AUTH_USER_MODEL` | 计划禁止；ADR 判定风险过高 |
| 给 `Admin`/`Student`/`Teacher` 加列 | 会与 R2.0 身份迁移冲突，只在原型 `Account` 加字段 |
| 对 `smass` 执行 `ALTER TABLE ... CONVERT TO utf8mb4` | 只做了隔离演练 |
| 注册 Windows 计划任务 | 需显式授权 |
| 安装 `pip-audit` 并扫描 | 未获授权安装第三方扫描器 |
| 大规模 UI 改版（BS3/BS5 统一） | 计划明确留待后续 |
| 远程 push | 计划禁止 |
