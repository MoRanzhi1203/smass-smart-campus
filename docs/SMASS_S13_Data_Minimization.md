# S13 数据最小化、保留控制与受控披露

> 状态：**TESTED**（25 例：服务 17 + 页面 7 + Chromium E2E 1）
> 代码：`smass_privacy/`、`templates/s13/`、`smass/settings_s13.py`、`smass/urls_s13.py`
> 隔离库：`smass_s13_privacy`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 字段分级 | public/internal/sensitive/personal 四级 + 导出脱敏方式 | `test_bad_classification`、`test_fields_of` |
| 敏感强制脱敏 | `sensitive/personal` 即使配置 `none`，导出也按 `partial` 处理 | `test_sensitive_forces_partial_mask` |
| 最小化导出 | 只导出已登记字段；未登记字段被忽略 | `test_minimized_rows_only_registered` |
| 导出确定性 | 同数据同顺序，SHA-256 可复现 | `test_export_digest_deterministic` |
| 披露申请 | 字段必须登记、用途必填、至少一个字段 | `test_request_validation` |
| 双人原则 | 不能审批自己提交的披露申请；只有管理员可批 | `test_self_approval_denied`、`test_student_cannot_approve` |
| 执行前置 | 必须已批准；执行生成行数/SHA-256 并写日志 | `test_full_flow`、`test_execute_requires_approval` |
| 不可重复执行 | 已执行再执行拒绝 | `test_execute_twice_rejected` |
| 保留控制 | 按 `retention_days` 清理过期样本；0 表示不清理 | `test_purge_expired_samples`、`test_no_retention_keeps_data` |
| 日志 append-only | 披露日志不可改/删 | `test_log_append_only` |
| 下载权限 | 仅申请人或管理员可下载，且必须已执行 | `test_export_requires_executed` |
| 页面流程 | 配置 → 申请 → 批准 → 执行 → 下载脱敏 CSV | `test_full_flow_with_masked_export`、浏览器 E2E |

## 2. 设计要点

- **最小化在服务层**：`minimized_rows` 只输出已登记字段并完成脱敏，视图拿不到原始值；
- **披露三步**：申请 → 审批（禁自批）→ 执行；执行时锁行，避免重复导出；
- **导出不落敏感原文**：CSV 只在下载时按同一确定性规则重新生成，库中只存摘要与行数；
- **保留期按资源取最小 retention**：同一资源多字段时以最严格保留期为准；
- **URL 顺序**：`export/` 必须在 `<action>/` 之前，否则会被当成 action 处理（本轮修复）。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_privacy --settings=smass.settings_s13 --noinput
```

实测（2026-10-30）：**25 例 OK**（服务 17 + 页面 7 + Chromium E2E 1）。

> 若上次测试异常中断，测试库可能残留；`--noinput` 会自动删除并重建 `test_smass_*` 库。

## 4. 已知边界

1. 保留期只作用于 `PrivacySample` 合成样本，真实业务表的清理需按表逐个接入并留运维审批；
2. 披露导出只支持 `student_record` 资源（其余资源需注册取值器）；
3. 未实现"数据主体查询/删除权"（DSR）流程，需与 S10 双人审批结合扩展；
4. CSV 未加密，生产应经加密通道并加下载水印/一次性链接。
