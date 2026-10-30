# S10 敏感操作再认证与双人审批

> 状态：**TESTED**（26 例：服务 19 + 页面 6 + Chromium E2E 1）
> 代码：`smass_stepup/`、`templates/s10/`、`smass/settings_s10.py`、`smass/urls_s10.py`
> 隔离库：`smass_s10_stepup`；同时装载 `smass_mfa` 以支持 TOTP 再认证

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 敏感操作注册表 | 4 类操作（导出敏感数据/重置他人密码/批量删除/授予高权限角色），各带 TTL 与双人要求 | `test_unknown_action` |
| 再认证（密码） | 校验账号密码，成功写 `StepUpProof`（默认 5 分钟） | `test_password_proof`、`test_wrong_password` |
| 再认证（TOTP） | 复用 S09 TOTP，需已绑定 MFA | `test_totp_proof` |
| 证明过期 | 过期后必须重新认证 | `test_proof_expires` |
| 未认证不能发起 | 抛出 `STEPUP_REQUIRED`，页面跳转再认证 | `test_open_requires_stepup`、`test_open_without_stepup_redirects_to_verify` |
| 双人审批 | 发起人 ≠ 审批人；审批人需管理员/管理角色 | `test_self_approval_denied`、`test_other_admin_approves`、`test_student_cannot_approve` |
| 载荷完整性 | 工单保存规范化载荷 SHA-256；批准/执行前复核，篡改即拒绝 | `test_tampered_payload_rejected`、`test_open_and_digest` |
| 执行前置 | 必须"已批准"；只能发起人或审批人执行 | `test_execute_before_approval_rejected` |
| 执行日志 | 执行写 `OperationLog`（append-only） | `test_execute_writes_log` |
| 不可重复执行 | 已执行再执行拒绝 | `test_execute_twice_rejected` |
| 驳回 | 必须填写原因 | `test_reject_requires_reason` |
| 超时过期 | 待审批超过 60 分钟自动 `expired` | `test_stale_approval_expires` |
| 数据范围 | 学生只看自己发起的工单 | `test_scoping`、`test_student_sees_only_own_approvals` |

## 2. 设计要点

- **两段门禁**：先再认证（短期证明），再双人审批（第二人），最后执行；
- **载荷摘要防篡改**：`sha256(json.dumps(sort_keys=True))`，批准与执行前都复核；
- **执行幂等与并发**：`select_for_update` 锁工单，状态变更与写日志同事务；
- **日志 append-only**：`OperationLog.save/delete` 对已存在记录抛错；
- **与 S09 协同**：再认证可选 TOTP，复用 S09 的验证与失败计数。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_stepup --settings=smass.settings_s10
```

实测（2026-10-30）：**26 例 OK**（服务 19 + 页面 6 + Chromium E2E 1）。

## 4. 已知边界

1. 再认证证明存于数据库而非仅 session，**多标签页共享**；如需严格单标签页可改为 session 级；
2. 工单载荷只存摘要与业务字段，不存敏感原文；
3. 未实现"审批人组/值班审批"与超时提醒（通知能力待统一通知服务）；
4. 敏感操作注册表在代码中定义，尚未做成后台可配置（需管理员 UI 与审计）。
