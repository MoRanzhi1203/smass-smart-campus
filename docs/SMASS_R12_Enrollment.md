# R12 自动分班、转专业与学籍异动

> 状态：**TESTED**（43 例：服务 27 + 页面 13 + 浏览器 E2E 3）
> 代码：`smass_enrollment/`（models / services / views / urls / migrations / tests）、
> `templates/r12/`、`smass/settings_r12.py`、`smass/urls_r12.py`
> 隔离库：`smass_r12_enrollment`（测试库 `test_smass_r12_enrollment`）

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 自动分班 | `PlacementRule` + `create_placement_preview` / `apply_placement` | `test_preview_does_not_touch_records`、`test_apply_writes_records_and_history` |
| 分班可预览、可回滚 | 预览只写批次与计划，执行写档案，回滚按批次恢复 | `test_rollback_restores_original_unit`、`test_rollback_refused_when_class_changed_after_apply` |
| 容量约束 | `capacity_per_class`；候选超总容量时**预检拒绝**，不产生任何写入 | `test_capacity_exceeded_is_rejected_before_any_write` |
| 合理均衡 | `strategy=balanced` + `balance_keys`（性别/生源地等），组内轮流进最少人的班 | `test_balanced_strategy_splits_gender_evenly` |
| 候选正确性 | 只含在读、未编班、属于本专业的档案 | `test_already_placed_records_are_excluded`、`test_other_major_records_are_excluded` |
| 转专业全流程 | 提交 → 审批 → 编入目标班级生效，写 unit/major 两条变更历史 | `test_full_flow_approve_and_apply`、`test_transfer_submit_approve_apply`（浏览器） |
| 职责分离 | 审批人 ≠ 提交人；学生无审批权 | `test_self_approval_is_denied`、`test_manager_cannot_approve_own_submission`、`test_student_cannot_approve` |
| 非法状态 | 同专业、重复申请、空理由、未批准就生效、班级不属于目标专业全部拒绝 | `test_same_major_is_rejected`、`test_duplicate_active_request_is_rejected`、`test_apply_requires_approved_state`、`test_apply_requires_class_of_target_major` |
| 学籍异动状态机 | 在读↔休学、在读/休学→退学/转出、在读→毕业；终态不可再变 | `test_suspend_and_resume`、`test_illegal_transition_is_rejected`、`test_terminal_status_blocks_further_change` |
| 离校类必填原因 | 退学/毕业/转出必须填写原因 | `test_withdraw_requires_reason` |
| 生效前状态漂移 | 审批后状态被其他流程改写则拒绝生效 | `test_apply_refused_when_status_drifted` |
| 页面与权限 | 未登录 302；学生访问分班页 403；学生只看到自己的申请 | `test_requires_login`、`test_student_forbidden_on_placement_pages`、`test_student_only_sees_own_transfers` |
| 浏览器 E2E | 转专业、分班、异动三条链路真实 Chromium 流程 | `test_r12_browser.py` 3 例 |

## 2. 设计要点

### 2.1 只碰 R4 档案，不改旧身份表

学籍权威是 `smass_organization.StudentRecord`，班级/专业复用 `OrganizationUnit`
（`unit_type='class'/'major'`）。R12 **不修改** `app01` 的三张身份表，也不新增密码源。

### 2.2 分班是"两阶段提交"

1. **预览**：写 `PlacementBatch(preview)` + `PlacementAssignment(planned)`，档案不动；
2. **执行**：在事务内逐条 `select_for_update` 档案，写 `unit`，并追加
   `StudentRecordChange`（含原值/新值/批次/操作者）；
3. **回滚**：仅当档案仍停留在本批次分配的班级时才恢复，否则拒绝，
   避免把后续转专业/异动的结果覆盖掉。

容量在预览阶段就校验（`候选数 > 总容量` 直接拒绝），不会出现"执行一半失败"。

### 2.3 审批与生效分离

- 提交：学生本人（或教务代提交）；
- 审批：具备 `update` 或 `manage_roles` 的账号，且**不能是提交人**；
- 生效：管理员指定目标班级后才改档案，转专业同时记录 `unit` 与 `major` 两条变更。

学籍异动的目标状态在**行锁内**由当前状态重新推导，避免并发下用过期状态生效。

### 2.4 MySQL 条件唯一约束不生效的处理

`r12_uniq_active_transfer` / `r12_uniq_active_status_change` 是条件唯一约束，
MySQL 不支持（Django `models.W036`），因此**服务层是唯一权威**：

- 提交时先 `select_for_update` 锁档案行，再检查"是否已有进行中申请"，
- 同一学生的并发双提交会被串行化，后到者必然看到前者的进行中记录。

### 2.5 页面

- `/r12/placement/`：规则卡片（候选数/班级/容量）+ 生成预览 + 批次列表；
- `/r12/placement/<pk>/`：批次统计与明细 + 执行/回滚；
- `/r12/transfers/`：提交表单（管理员可选档案）+ 申请列表 + 批准/驳回/生效/撤销；
- `/r12/status/`：提交异动 + 记录列表 + 批准/驳回/确认生效。

全部页面无外部 CDN 依赖，表格有表头，按钮为原生表单（禁用 JS 也能完成审批）。

## 3. 状态机

```
学籍状态：enrolled（在读） ⇄ suspended（休学）
          enrolled/suspended → withdrawn（退学）
          enrolled → graduated（毕业）
          enrolled → withdrawn（转出，语义由 change_type 区分）

转专业：submitted → approved → effective
        submitted → rejected
        submitted → cancelled

分班批次：preview → applied → rolled_back
```

终态（`withdrawn` / `graduated`）不再允许任何异动或转专业。

## 4. 数据与安全

- 新增表：`PlacementRule` / `PlacementBatch` / `PlacementAssignment` /
  `MajorTransferRequest` / `StudentStatusChange`；
- 不存储密码、身份证号等敏感字段；理由文本截断到 500 字；
- 所有写操作走服务层并写审计日志（`smass.audit`：批次、申请、审批、生效）；
- 正式库 `smass` 未执行迁移（只读策略），上线需走授权发布流程。

## 5. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_enrollment --settings=smass.settings_r12
```

实测（2026-10-30）：

| 套件 | 例数 | 结果 |
|---|---|---|
| `test_r12_services` | 27 | OK |
| `test_r12_ui` | 13 | OK |
| `test_r12_browser`（Chromium） | 3 | OK |
| 合计 | **43** | **OK** |

## 6. 已知边界（需学校政策输入）

1. 分班的"成绩均衡"依赖 `StudentRecord.extra['score']`，真实成绩来源未授权接入，
   当前作为可选维度，缺失时按其它维度或顺序分配；
2. 转专业的目标班级容量未强制（学校可能按计划数控制），需政策确认后加硬约束；
3. 年级标签 `grade_label` 仅作展示与筛选，未与 `OrganizationUnit(grade)` 强绑定；
4. 转专业的"生效日期"目前为即时生效，学期边界生效需教务政策确认。
