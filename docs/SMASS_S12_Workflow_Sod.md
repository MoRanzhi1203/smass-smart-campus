# S12 工作流职责分离与禁止自批（验收报告）

- 实现：`smass_workflow/services.py`、`smass_workflow/models.py`
- 回归：`smass_workflow/tests/test_s12_sod.py`（6 例）
- 全量回归：`smass_workflow` 47 例通过

## 1. 规则

| 规则 | 实现 |
|---|---|
| 发起人 ≠ 审批人 | `transition()` 比较 `actor` 与 `instance.created_by`，审批动作直接拒绝 |
| 发起人仍可提交/撤回 | `SELF_SERVICE_ACTIONS = {submit, withdraw, cancel, resubmit}` |
| 越级审批拒绝 | `_allowed()` 只接受当前节点配置的 `(from_node, action)` 转移 |
| 审批链追加不可改 | `WorkflowEvent.save()` 阻止更新、`delete()` 阻止删除 |
| 并发保护 | `transition()` 以 `version_no` 条件更新，冲突抛 `ConflictError` |

## 2. 测试覆盖

```bash
python manage.py test smass_workflow --settings=smass.settings_r6
```

| 用例 | 断言 |
|---|---|
| 发起人提交 | `submit` 成功，进入审批节点 |
| 发起人自批 | 抛 `TransitionError`，含"职责分离" |
| 他人审批 | 状态变为 `approved` |
| 发起人撤回 | 状态为 `withdrawn` |
| 越级审批 | 从 start 直接 `approve` 被拒绝 |
| 事件链不可变 | 顺序 `create → submit → approve`；修改/删除抛 `ValidationError` |

## 3. 修复的真实缺陷

`_status_for()` 原先先判断目标节点是否为 `end`，导致
"撤回（withdraw）指向 end 节点"被误判为 `approved`。
已改为**撤回优先**，并补充测试证明。

## 4. 边界

- 审批人身份来自调用方的 `actor` 参数；接入页面时需从已认证会话取值，不能信任表单。
- `QuerySet.update()` 可绕过模型 `save()`；生产写入统一走 `services`，不直接 update 审计表。
- 多级会签/或签规则未实现，当前是"逐节点审批"。
