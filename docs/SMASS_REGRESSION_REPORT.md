# SMASS 全量回归报告（REGRESSION）

> 状态：**TESTED**
> 入口：`scripts/r10_full_regression.py --json`（已扩展覆盖 DSH 新增模块）
> 证据：`.local/evidence/regression/r10_full_run.log`、`smass_operations_rerun.log`

## 1. 范围

31 个测试套件，覆盖 TRAE 时代全部模块（R4–R11、R16、R21/R22、app01、tests_e2e）
与 DSH 新增模块（R12–R20、S09–S19）。

## 2. 首轮结果（2026-10-31 00:16–01:05）

| 套件 | settings | 例数 | 结果 | 耗时 |
|---|---|---|---|---|
| smass_operations | settings_r10 | 425 | **FAILED（4F / 1E / 5S）** | 416.0s |
| smass_analytics | settings_r7 | 31 | OK | 33.7s |
| smass_organization | settings_r4 | 72 | OK | 118.7s |
| smass_data_exchange（s25_roundtrip + s25_ui） | settings_r4 | 60 | OK | 28.2s |
| smass_data_exchange（s25_r5） | settings_r5 | 25 | OK | 24.1s |
| smass_academic | settings_r5 | 56 | OK | 58.6s |
| smass_facilities | settings_r16 | 59 | OK | 50.4s |
| smass_scheduling | settings_r11 | 40 | OK | 44.7s |
| smass_workflow | settings_r6 | 47 | OK | 27.6s |
| smass_api | settings_r8 | 23 | OK | 11.5s |
| r22_account | settings_r22 | 117 | OK | 53.6s |
| r21_account | settings_r21 | 110 | OK | 71.7s |
| app01 | formal | 188 | OK | 87.6s |
| tests_e2e | formal | 16 | OK | 40.4s |
| smass_enrollment | settings_r12 | 43 | OK | 56.7s |
| smass_attendance | settings_r13 | 41 | OK | 51.3s |
| smass_activities | settings_r14 | 28 | OK | 45.9s |
| smass_clubs | settings_r15 | 28 | OK | 56.2s |
| smass_forum | settings_r17 | 32 | OK | 70.6s |
| smass_finance | settings_r18 | 34 | OK | 62.9s |
| smass_party | settings_r19 | 35 | OK | 55.1s |
| smass_portal | settings_r20 | 26 | OK | 60.0s |
| smass_uploads | settings_s14 | 27 | OK | 37.5s |
| smass_audit | settings_s16 | 20 | OK | 24.5s |
| smass_security_tests | settings_security | 20 | OK | 45.5s |
| smass_mfa | settings_s09 | 24 | OK | 24.3s |
| smass_stepup | settings_s10 | 26 | OK | 40.0s |
| smass_policy | settings_s11 | 25 | OK | 42.2s |
| smass_privacy | settings_s13 | 25 | OK | 39.5s |
| smass_api_security | settings_s15 | 28 | OK | 45.0s |
| smass_a11y | settings_s19 | 19 | OK | 22.1s |

首轮合计：**1750 例，30/31 套件 OK，1 套件失败（4 failures + 1 error + 5 skipped）**。

## 3. 失败分析：S12 职责分离与 R10 旧夹具冲突

失败项（全部在 `smass_operations`）：

| 测试 | 现象 |
|---|---|
| `test_submit_then_approve` | `'pending' != 'approved'` |
| `test_reject_sets_rejected` | `'pending' != 'rejected'` |
| `test_full_journey_with_audit` | `'pending' != 'approved'` |
| `test_full_journey_persists_each_step` | `'pending' != 'approved'` |
| `test_full_chain`（error） | 同上，`transition` 抛错 |

**根因**：S12 引入职责分离规则——`actor == created_by` 时禁止 approve/reject：

```python
if (actor and instance.created_by and actor == instance.created_by
        and action not in SELF_SERVICE_ACTIONS):
    raise TransitionError('职责分离：不能审批自己提交的流程')
```

而 R10 的测试夹具用**同一个管理员**（`U5ADM` / `R10E2E`）既发起又审批，
在 S12 生效后必然被拒绝（HTTP 400，状态保持 pending）。

**判定**：产品规则正确（禁止自审是安全要求，S12 已单独验收），**测试夹具过时**。
不能为了过测试而放宽规则。

## 4. 修复

只改测试夹具，不改产品代码、不放宽规则：

| 文件 | 修改 |
|---|---|
| `smass_operations/tests/test_r10_u5_r6.py` | 新增 `U5AP` 审批账号；`approve`/`reject` 前 `force_login(approver)`；端到端流程改为「提交（发起人）→ 审批（另一人）」 |
| `smass_operations/tests/test_r10_u8_routes.py` | 审批前创建 `U8AP` 并切换登录 |
| `smass_operations/tests/test_r10_release.py` | `transition(..., 'approve', actor='R10AP')`（原为发起人 `R10E2E`） |

修改后：3 个测试模块 **54 例全部 OK**（42.1s）。

## 5. 复跑结果

| 套件 | 例数 | 结果 | 耗时 |
|---|---|---|---|
| smass_operations（修复后） | 425 | **OK（skipped=5）** | 418.2s |

`smass_operations_rerun.log` 中 `Ran 425 tests … OK (skipped=5)`，退出码 0。

因此**全量 31 套件、1750 例最终全部通过**：
30 个套件首轮 OK + `smass_operations` 修复后 425 例 OK。

## 6. 浏览器 E2E 覆盖

| 文件 | 用例数 |
|---|---|
| tests_e2e/test_browser.py | 16 |
| smass_operations/tests/test_r10_u8_browser.py | 21 |
| smass_academic/tests/test_r5_browser.py | 8 |
| r22_account/tests/test_g7_browser.py | 8 |
| smass_organization/tests/test_r4_browser.py | 7 |
| smass_workflow/tests/test_r6_browser.py | 7 |
| smass_analytics/tests/test_r7_browser.py | 6 |
| r22_account/tests/test_c_browser_matrix.py | 5 |
| r21_account/tests/test_browser_r21.py | 4 |
| smass_enrollment/tests/test_r12_browser.py | 3 |
| smass_attendance/tests/test_r13_browser.py | 2 |
| smass_facilities/tests/test_r16_browser.py | 2 |
| smass_a11y/tests/test_s19_browser.py | 2 |
| 其余 14 个模块各 1 | 14 |
| **合计** | **104** |

## 7. 结论

- 30/31 套件首轮通过；唯一失败源于**安全规则与旧测试夹具冲突**，已按"改夹具、不改规则"修复；
- 修复仅触及 `smass_operations` 的三个测试文件，产品代码零改动；
- 全量 1750 例（含 104 个 Chromium E2E）在修复后全部通过（见第 5 节复跑结果）；
- 5 个 `skipped` 为 R10 模块内既有的环境性跳过（浏览器探针依赖），非本轮引入。
