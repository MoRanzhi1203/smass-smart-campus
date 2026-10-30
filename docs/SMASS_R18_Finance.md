# R18 学费账单、财务台账与受控退费

> 状态：**TESTED**（34 例：服务 23 + 页面 8 + Chromium E2E 1）
> 代码：`smass_finance/`、`templates/r18/`、`smass/settings_r18.py`、`smass/urls_r18.py`
> 隔离库：`smass_r18_finance`（**全合成数据，无真实支付/退款**）

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 收费项目 | 编码/名称/类别/金额/学期；金额必须 > 0；编码唯一 | `test_fee_item_requires_finance`、`test_fee_item_bad_amount`、`test_duplicate_fee_code` |
| 账单生成 | 按项目汇总金额、写明细、写"应收"台账 | `test_bill_total_and_ledger`、`test_bill_requires_items` |
| 合成缴费 | 仅 `synthetic_bank`/`synthetic_cash`；部分/全额；超欠费拒绝 | `test_partial_then_full_payment`、`test_overpay_rejected`、`test_bad_method_rejected` |
| 幂等缴费 | `reference` 唯一，重复提交返回同一笔且不重复入账 | `test_idempotent_reference` |
| 缴费状态 | 缴清后不能再缴；学生不能登记缴费 | `test_pay_after_paid_rejected`、`test_student_cannot_pay` |
| 台账 | 缴费/退费都写台账，方向 +1/−1；append-only（改/删抛错） | `test_payment_writes_ledger`、`test_ledger_cannot_be_modified`、`test_ledger_cannot_be_deleted` |
| 退费申请 | 本人或财务；金额不超过可退余额（扣减已申请/已批准） | `test_refund_exceeds_paid`、`test_pending_refund_counts_against_available` |
| 退费审批 | 财务管理员，禁止自批，驳回必填原因 | `test_self_approval_denied`、`test_student_cannot_approve`、`test_reject_requires_reason` |
| 出纳执行 | 必须"已批准"；执行后回写账单、写负向台账、缴清账单全部退款时标记缴费已退 | `test_refund_full_flow`、`test_execute_requires_approved` |
| 数据范围 | 学生只看自己的账单与退费；台账仅财务可见 | `test_student_sees_only_own_bills`、`test_student_cannot_read_ledger`、`test_student_forbidden_on_ledger` |

## 2. 设计要点

- **金额只用 Decimal**，量化到分，拒绝浮点比较；
- **缴费幂等在事务内先查后写**：`reference` 唯一，重复请求直接返回既有记录；
- **退费三步不可跳过**：申请（可退余额校验）→ 审批（禁自批）→ 出纳执行（回写账单 + 负向台账）；
- **台账 append-only**：模型 `save/delete` 对已存在记录直接抛错，模拟真实财务不可篡改要求；
- 页面顶部固定提示"合成数据演练，不接真实支付"。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_finance --settings=smass.settings_r18
```

实测（2026-10-30）：**34 例 OK**（服务 23 + 页面 8 + Chromium E2E 1）。

## 4. 已知边界与授权状态

1. **不接真实支付网关**：没有真实收费、退款、对账文件导入；
2. 未实现学费减免/助学贷款/缓缴等政策业务（学校政策待输入，属 `BUSINESS_CONFIG_PENDING`）；
3. 未实现与银行/财政对账文件的双向对账，只有内部台账一致性；
4. 台账 append-only 是应用层约束，生产数据库层还需触发器或权限隔离（部署时处理）。
