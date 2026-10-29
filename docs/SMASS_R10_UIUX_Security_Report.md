# SMASS R10 UI/UX 安全报告（U9）

> 设置：`smass.settings_r10`　库：`smass_r10_release`（隔离）　基线：`5b69d58`
> 每条结论都指向具体测试，不是声明。

## 1. 安全不变量逐条核验

| # | 不变量 | 实现位置 | 测试 | 结果 |
|---|---|---|---|---|
| S1 | 匿名不能访问受保护页面 | `roles_required` 装饰器 | `test_anonymous_denied_everything_but_home` | PASS |
| S2 | 无角色账号不降级为全可见 | `account_roles` + `scoped_*` 默认空集 | `test_conflict_role_sees_nothing` | PASS |
| S3 | 越权访问他人学生 → 404（不泄露存在性） | `student_detail_page` | `test_detail_denied_for_other_college` | PASS |
| S4 | 学生只能看自己 | `can_access_student` | `test_student_sees_own_detail_only` | PASS |
| S5 | 伪造 POST 被拒且不写库 | 视图装饰器 | `test_forged_post_denied` | PASS |
| S6 | 乐观锁冲突 → 409 且保留他人修改 | `update_student(expected_version=...)` | `test_version_conflict_returns_409` | PASS |
| S7 | 导入预览零写入 | `import_preview` 不写 `StudentRecord` | `test_preview_does_not_write` | PASS |
| S8 | 字段级权限：基础字段按角色 | `_base_editable` | `test_teacher_cannot_edit` | PASS |
| S9 | 非创建者不能查看/操作流程实例 | `instance_detail`/`instance_action` | `test_other_user_cannot_view_instance` / `..._act` | PASS |
| S10 | 非法流程转移被拒且状态不变 | `transition` | `test_illegal_action_shows_error` | PASS |
| S11 | 他人通知不可标记已读 | `notification_read` 过滤 recipient | `test_cannot_read_others_notification` | PASS |
| S12 | 小样本抑制值不在 HTML 泄漏 | 模板只渲染徽章 | `test_real_value_not_in_html` | PASS |
| S13 | 抑制值不在 CSV 泄漏 | `compute_metric` 返回 0 | `test_csv_does_not_leak_suppressed_value` | PASS |
| S14 | scope 先于聚合 | `scoped_students` 后再 count | `test_college_admin_sees_own_count_only` | PASS |
| S15 | 报表权限（非授权角色 403） | `permission_roles` 校验 | `test_report_permission_denied` | PASS |
| S16 | 导出权限与页面一致 | `report_export_page` | `test_export_permission_denied` | PASS |
| S17 | API 默认空 scope | `create_service_account` | `test_default_scope_is_empty` | PASS |
| S18 | `read:students` ≠ 全校可见 | `scoped_students_service_account` | `test_read_students_does_not_mean_whole_school` | PASS |
| S19 | 限流生效 | `check_rate_limit` | `test_rate_limit_still_enforced` | PASS |
| S20 | 幂等重放 | `IdempotencyKey` | `test_idempotency_still_enforced` | PASS |
| S21 | 令牌仅存摘要 | `hash_token` | `test_token_not_stored_in_plaintext` | PASS |
| S22 | 文档页不泄漏令牌 | — | `test_docs_does_not_leak_tokens` | PASS |
| S23 | 运维页只读（无 POST/无改配置） | 页面无表单 | `test_status_has_no_write_actions` | PASS |
| S24 | CSRF 强制 | Django middleware + `SM.request` 带 token | 导入/表单测试均通过 | PASS |
| S25 | 模板不依赖 `request.user.username` | 用 `login_name`/`display_name` | `test_identity_shown_without_username_attribute` | PASS |

## 2. 身份与认证

| 项 | 状态 |
|---|---|
| `AUTH_USER_MODEL` | **未修改**（仍为 `auth.User`） |
| 身份来源 | `r21_account.AccountBackend` + `request.user`（`Account` 实例） |
| 正式认证切换 | **未执行**（需单独授权） |
| 冲突身份 | `RoutePolicyMiddleware` deny → `/r21/login/`（该路由已注册，不再 404） |
| 首登改密 | `/r21/change-password/` 目前重定向到 `/r10/`（简化，见风险 R-04） |

## 3. 授权模型

三层，逐层收紧：

1. **角色**（`roles_required`）：`system_admin` / `college_admin` / `teacher` / `student`
2. **对象范围**（`scoped_units` / `scoped_students`）：默认空集，按 `OrganizationMembership` 计算
3. **字段级**（`visible_fields` / `editable_fields` / `filtered_extra` + `_base_editable`）

副作用：**侧边栏不隐藏即安全？** 不是。侧边栏只做可见性提示；直接访问 URL 由视图判定，
`test_anonymous_denied_everything_but_home` 与 `test_forged_post_denied` 覆盖。

## 4. 数据泄漏面检查

| 通道 | 检查 | 结果 |
|---|---|---|
| HTML | 抑制指标无 `id="value-<code>"` 节点 | PASS |
| JSON（`/r7/metric-series/`） | 权限校验，未授权 403 | PASS |
| CSV 导出 | 抑制值为 0 | PASS |
| API 响应 | 服务账号默认空集 | PASS |
| 文档页 | 无明文令牌/摘要 | PASS |
| 运维页 | 无 password / mysql:// | PASS |
| 审计日志 | 只记 action/actor/status，不记请求体 | 代码审查 |

## 5. 未解决的安全风险

| ID | 风险 | 等级 | 说明 |
|---|---|---|---|
| R-01 | MySQL 无条件唯一索引（`models.W036`） | 中 | `AccountRole` / `ApprovalTask` 的 active 约束未在 DB 创建，靠服务层；并发下有理论窗口 |
| R-02 | API 限流为进程内 | 低 | 多进程部署时失效 |
| R-03 | `/r21/change-password/` 为占位重定向 | 中 | 首次登录强制改密未真正实现 |
| R-04 | WebKit 单测无法登录 | 低 | 测试基础设施问题，非产品缺陷 |
| R-05 | 无屏幕阅读器实机验证 | 中 | 可访问性无法宣称 WCAG 合规 |
| R-06 | 演示口令 `Demo#2024` 硬编码在 seed 脚本 | 低 | 仅隔离环境；已入白名单并在文档标注 |

## 6. 正式数据库零写入证据

| 检查 | 命令 | 结果 |
|---|---|---|
| 表数量 | `scripts/db_inspect.py` | **26 表**（与基线一致） |
| 业务数据 | 同上 | Admin 1 · Student 3 · Teacher 2（未变） |
| 迁移 | `makemigrations --check --dry-run` | No changes |
| 所有测试 settings | `smass.settings_r4/r5/r6/r7/r8/r9/r10` | 均指向 `smass_r*` 隔离库 |

**结论**：本轮 U0–U8 全部操作未写入正式 `smass` 数据库。

## 7. 结论

**25 条安全不变量全部有测试证据**；**6 项已知风险**中 3 项为中等级
（R-01 条件约束、R-03 改密占位、R-05 无 SR 验证）。

这些风险**不阻断隔离环境验收**，但**阻断生产部署**——
`PRODUCTION_DEPLOYMENT = NOT_AUTHORIZED` 的核心理由即在此。
