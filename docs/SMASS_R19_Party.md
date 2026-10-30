# R19 党建及专项组织受控通用功能

> 状态：**TESTED**（35 例：服务 26 + 页面 8 + Chromium E2E 1）
> 代码：`smass_party/`、`templates/r19/`、`smass/settings_r19.py`、`smass/urls_r19.py`
> 隔离库：`smass_r19_party`
> **边界：不承载真实党建材料，`summary` 仅为合成摘要；真实数据接入需另行授权。**

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 组织建模 | 党支部/党委/专项工作组，自引用上级，可标记敏感级别 | `test_create_org_requires_party_admin`、`test_duplicate_org_code` |
| 成员管理 | 添加/移除成员、政治面貌、重复成员拒绝 | `test_add_and_remove_member`、`test_duplicate_member_rejected` |
| 组织生活/活动 | 三会一课/主题党日/志愿服务/教育培训，计划→完成/取消 | `test_activity_lifecycle` |
| 资料三级密级 | 公开（登录可见）/内部（本组织成员）/敏感（需授权或按次审批） | `test_public_visible_to_all`、`test_internal_requires_membership`、`test_sensitive_denied_by_default` |
| 未授权脱敏 | 未授权访问返回受控占位，不返回摘要 | `test_view_document_masks_and_audits`、`test_sensitive_document_masked_and_request` |
| 访问审计 | view/deny/request/approve/reject 全记录，append-only | `test_view_document_allowed_writes_view_log`、`test_audit_cannot_be_modified`、`test_audit_cannot_be_deleted` |
| 按次借阅 | 申请（用途必填、重复拒绝）→ 审批（禁自批、有效期）→ 到期失效 | `test_request_and_approve`、`test_duplicate_request`、`test_expired_request_denied` |
| 长期授权 | 管理员授予/撤销敏感权限；不能给自己授权 | `test_self_grant_denied`、`test_grant_and_revoke`、`test_expired_grant` |
| 权限边界 | 只有党务管理员可创建/维护；学生不能读审计 | `test_student_cannot_read_audit`、`test_student_forbidden_on_audit` |
| 数据范围 | 学生只看到公开 + 本组织内部资料；管理员看到全部 | `test_student_sees_public_and_member_internal`、`test_non_member_sees_only_public`、`test_admin_sees_all` |

## 2. 设计要点

- **最小可见**：资料列表只返回元数据；正文必须经 `view_document` 判定；
- **拒绝也留痕**：未授权访问写 `deny` 审计，便于发现异常探测；
- **双重授权模型**：账号级长期授权（`AccessGrant`）+ 按次借阅（`AccessRequest` 带有效期）；
- **职责分离**：不能审批自己的借阅，不能给自己授予敏感权限；
- 审计表 `save/delete` 对已存在记录抛错，应用层 append-only。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_party --settings=smass.settings_r19
```

实测（2026-10-30）：**35 例 OK**（服务 26 + 页面 8 + Chromium E2E 1）。

## 4. 已知边界与授权状态

1. **不处理真实党建敏感资料**：资料正文只有合成摘要；真实材料接入需单独授权与脱敏评审；
2. 未实现党费管理、组织关系转接、发展党员流程等专项业务（需学校组织部门政策输入）；
3. 访问审计的应用层 append-only 在生产需数据库触发器/权限隔离加固；
4. 敏感级别目前只有两档（普通/敏感），如需三级密级需扩展 `SENSITIVITY_LEVELS`。
