# S11 策略感知与字段级授权

> 状态：**TESTED**（25 例：服务 17 + 页面 7 + Chromium E2E 1）
> 代码：`smass_policy/`、`templates/s11/`、`smass/settings_s11.py`、`smass/urls_s11.py`
> 隔离库：`smass_s11_policy`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 默认拒绝 | 无策略 / 停用策略 / 无角色一律拒绝 | `test_default_deny_without_policy`、`test_disabled_policy_denies` |
| 读角色策略 | 策略内 `read_roles` 与账号角色求交 | `test_role_allowed`、`test_role_denied` |
| 写角色策略 | `write_roles` 独立于读角色 | `test_write_denied_by_default`、`test_write_allowed` |
| 业务状态条件 | `condition`（如 `{"status": ["enrolled"]}`）不满足即拒绝 | `test_condition_allows_and_denies` |
| 字段脱敏 | `none` / `partial`（保留首 3 尾 2）/ `full` | `test_partial_mask`、`test_full_mask` |
| 字段能力汇总 | `effective_fields` 一次给出读/写/脱敏 | `test_effective_fields` |
| 策略配置 | 只有管理员可配置；同资源同字段唯一（upsert） | `test_student_cannot_configure`、`test_policy_upsert` |
| 决策审计 | 每次读写判定写 `PolicyDecisionLog`（append-only） | `test_decision_log_written`、`test_decision_log_append_only` |
| 日志范围 | 只有管理员可看决策日志 | `test_logs_scoping` |
| 参数防护 | 预览页非法主键不 500 | `test_preview_with_invalid_record_param` |

## 2. 设计要点

- **与既有授权分工**：`r21_account.authorization` 负责 RBAC/组织域/对象级与静态字段白名单；
  本模块提供**可配置字段策略**（角色、状态条件、脱敏、审计），两者互补；
- **判定顺序固定**：策略存在 → 角色交集 → 状态条件 → 允许并脱敏，任一步失败即拒绝；
- **脱敏在服务层完成**：视图拿不到原始值，避免"模板忘了脱敏"；
- **决策日志 append-only**：与 S16 审计互补（S16 是事件链，S11 是字段级细粒度）。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_policy --settings=smass.settings_s11
```

实测（2026-10-30）：**25 例 OK**（服务 17 + 页面 7 + Chromium E2E 1）。

## 4. 已知边界

1. 策略目前是"扁平资源#字段"，未支持按组织域细分（可扩展 `scope` 字段）；
2. 条件只支持等值与集合匹配，不支持表达式（如需复杂规则应接策略引擎）；
3. 决策日志每字段一次写入，生产高并发需采样或异步落库；
4. 未提供策略变更历史（`FieldPolicy` 直接覆盖），变更审计依赖 S16 事件链。
