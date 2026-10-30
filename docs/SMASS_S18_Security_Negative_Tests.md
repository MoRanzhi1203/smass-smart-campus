# S18 跨模块安全负向测试集

> 状态：**TESTED**（20 例负向测试全通过；同时修复 6 处 500 缺陷）
> 代码：`smass_security_tests/`、`smass/settings_security.py`、`smass/urls_security.py`
> 隔离库：`smass_security_suite`；组合 URLConf 同时装载 R12/R13/R14/R15/R17/R18/R19 + S14/S16

## 1. 覆盖矩阵

| 类别 | 攻击/负向场景 | 断言 | 用例 |
|---|---|---|---|
| IDOR | 访问他班考勤会话 | 403 | `test_cannot_view_other_class_session` |
| IDOR | 取消他人活动报名 | 403 且状态不变 | `test_cannot_cancel_others_registration` |
| IDOR | 删除他人帖子 | 403 且帖子仍 published | `test_cannot_remove_others_post` |
| IDOR | 读取他人账单 | 403 | `test_cannot_read_other_bill` |
| IDOR | 退出他人社团成员 | 403 且仍 active | `test_cannot_leave_others_membership` |
| IDOR | 撤销他人转专业申请 | 403 | `test_cannot_read_other_transfer` |
| 受控资料 | 学生访问敏感资料 | 200 但正文脱敏 | `test_sensitive_document_masked` |
| 越权 | 学生访问 6 个管理页（GET）+ 组织创建（POST） | 全部 403 | `test_student_forbidden_on_manage_pages` |
| 越权 | 教师访问考勤统计 | 200（正例） | `test_teacher_allowed_on_attendance_stats` |
| 未登录 | 访问管理页 | 302 → `/r21/login/` | `test_anonymous_redirected_to_login` |
| CSRF | 无令牌 POST（请假/评论/报名） | 全部 403 | `test_post_without_token_rejected` |
| XSS | 帖子标题含 `<script>` | 页面输出 `&lt;script&gt;`，无可执行标签 | `test_post_title_is_escaped` |
| XSS | 公告正文含 `onerror` | 不原样输出 | `test_announcement_body_escaped` |
| SQLi | 4 类注入 payload 打 stats/mark/bill 参数 | 均 < 500 | `test_stats_unit_param_injection_does_not_crash`、`test_session_mark_record_injection_does_not_crash`、`test_bill_create_injection_does_not_crash` |
| SSRF | 下载携带 `url=`/`next=` 外部地址 | 只返回本地文件字节 | `test_download_ignores_external_url_params` |
| 并发/重复 | 重复报名活动 | 拒绝且记录数仍 1 | `test_duplicate_activity_registration_idempotent` |
| 并发/重复 | 重复签到 | 幂等，记录数仍 1 | `test_duplicate_sign_in_idempotent` |
| 并发/重复 | 重复请假提交 | 拒绝 | `test_duplicate_leave_submit_rejected` |

## 2. 本轮由负向测试发现并修复的真实缺陷

| 缺陷 | 影响 | 修复 |
|---|---|---|
| 非法主键参数触发 `ValueError` → 500 | `/r13/stats/`、`/r13/sessions/<pk>/mark/`、`/r13/makeups/submit/`、`/r18/bills/create/`、`/r12/transfers/submit/`、`/r12/transfers/<pk>/apply/`、`/r15/clubs/<pk>/appoint/`、`/r19/orgs/<pk>/members/add/` 在被篡改参数时返回 500（信息泄露/可用性风险） | 统一 `_parse_pk()`：非数字返回 `None`，服务层再按"不存在"拒绝 |
| `teacher_mark` 收到 `None` 学生 | `NoneType.unit_id` → 500 | 服务层校验 `student is None` → `AttendanceError('学生不存在')` |

修复后已回归：R12 43 例、R13 41 例、R15 28 例、R18 34 例、R19 35 例，全部 OK。

## 3. 设计要点

- **组合 URLConf**：同一测试库内同时挂载多个业务模块，才能做真实跨模块 IDOR；
- **断言"不 500"而非"返回固定码"**：注入防御的目标是不崩、不泄露，具体状态码由业务决定；
- **正例与负例成对**：每类负向都有对应正例（教师可访问统计），避免"全 403"式假通过；
- **幂等验证看数据库**：重复提交后断言记录数，而不是只看响应码。

## 4. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_security_tests --settings=smass.settings_security
```

实测（2026-10-30）：**20 例 OK**；修复后回归 R12/R13/R15/R18/R19 共 **181 例 OK**。

## 5. 已知边界

1. 未覆盖文件上传的并发竞争（S14 已有单独用例）；
2. XSS 覆盖服务端模板转义，未做前端 DOM 型 XSS（无 SPA 前端）；
3. SSRF 覆盖"无外发请求入口"，未测试真实 URL 抓取功能（本系统未提供）；
4. SQLi 覆盖参数注入导致的异常路径，ORM 参数化本身由 Django 保证；
5. 未做速率限制相关负向（属 S23 容量/限流）。
