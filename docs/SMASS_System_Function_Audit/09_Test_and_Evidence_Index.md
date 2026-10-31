# 09 测试与证据索引

> 证据等级：
> **A** 可复现自动化测试（`manage.py test`）·
> **B** 可复现脚本输出（JSON/日志）·
> **C** 浏览器截图/E2E ·
> **D** 仅代码阅读（未运行）。
>
> 本轮不重复执行 1800 例全量回归，复用 `80c8d85` 的实测结果；
> 对产品层 40 例与只读探针做了本轮实际执行（见 §3）。

---

## 1. 全量回归（A，基线 `80c8d85`）

命令：`python scripts/r10_full_regression.py --json`
结果：**32 套件 / 1800 例 / 0 失败 / exit 0**（`.local/evidence/product/regression_rerun.log`）。

| 套件 | settings | 用例 | 耗时(s) | 结果 |
|---|---|---|---|---|
| smass_operations | smass.settings_r10 | 425 | 482.8 | PASS |
| smass_analytics | smass.settings_r7 | 31 | 47.1 | PASS |
| smass_organization | smass.settings_r4 | 72 | 175.1 | PASS |
| smass_data_exchange（roundtrip+ui） | smass.settings_r4 | 60 | 39.6 | PASS |
| smass_data_exchange（r5 adapters） | smass.settings_r5 | 25 | 32.3 | PASS |
| smass_academic | smass.settings_r5 | 56 | 81.9 | PASS |
| smass_facilities | smass.settings_r16 | 59 | 69.8 | PASS |
| smass_scheduling | smass.settings_r11 | 40 | 60.0 | PASS |
| smass_workflow | smass.settings_r6 | 47 | 38.2 | PASS |
| smass_api | smass.settings_r8 | 23 | 14.8 | PASS |
| r22_account | smass.settings_r22 | 117 | 75.7 | PASS |
| r21_account | smass.settings_r21 | 110 | 101.9 | PASS |
| app01 | formal | 188 | 121.5 | PASS |
| tests_e2e | formal | 16 | 58.2 | PASS |
| smass_enrollment | smass.settings_r12 | 43 | 75.9 | PASS |
| smass_attendance | smass.settings_r13 | 41 | 73.8 | PASS |
| smass_activities | smass.settings_r14 | 28 | 65.0 | PASS |
| smass_clubs | smass.settings_r15 | 28 | 69.9 | PASS |
| smass_forum | smass.settings_r17 | 32 | 72.4 | PASS |
| smass_finance | smass.settings_r18 | 34 | 66.2 | PASS |
| smass_party | smass.settings_r19 | 35 | 74.8 | PASS |
| smass_portal | smass.settings_r20 | 36 | 69.2 | PASS |
| smass_uploads | smass.settings_s14 | 27 | 50.5 | PASS |
| smass_audit | smass.settings_s16 | 20 | 35.9 | PASS |
| smass_security_tests | smass.settings_security | 20 | 62.1 | PASS |
| smass_mfa | smass.settings_s09 | 24 | 36.3 | PASS |
| smass_stepup | smass.settings_s10 | 26 | 98.2 | PASS |
| smass_policy | smass.settings_s11 | 25 | 96.9 | PASS |
| smass_privacy | smass.settings_s13 | 25 | 50.1 | PASS |
| smass_api_security | smass.settings_s15 | 28 | 42.3 | PASS |
| smass_a11y | smass.settings_s19 | 19 | 21.5 | PASS |
| **smass_workspace** | **smass.settings_product** | **40** | **68.5** | **PASS** |

> 首次全量中 `smass_api_security` 出现 1 例偶发失败；该套件单独重跑 28/28
> 通过，全量复跑全绿。回归脚本已增加失败尾部输出。

---

## 2. 产品层测试覆盖（A，`smass_workspace/tests/test_workspace.py` 40 例）

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| AuthFlowTests | 7 | 匿名跳转、登录页、三种落地、无角色、退出 POST |
| GuardMatrixTests | 9 | 学生/教师/辅导员/学院管理员/超管的 403 矩阵 |
| StudentWorkspaceTests | 4 | 15 页 200、课程可见、请假提交、撤销他人请假 |
| TeacherWorkspaceTests | 4 | 8 页 200、审批跨端同步、越权学生 403、本人学生 200 |
| CounselorScopeTests | 4 | 负责班级/学生、越权 403、请假审批页 |
| AdminConsoleTests | 10 | 19 页 200、学院范围、跨院 403、建课、越权建课 403、角色授予生效、公告可见、建场地、越权建场地 403 |
| SharedServiceTests | 2 | 三端 profile/notifications、旧入口重定向 |

运行：`python manage.py test smass_workspace --settings=smass.settings_product`

---

## 3. 本轮实际执行的只读验证（B/C）

| 验证 | 命令 | 结果 | 证据 |
|---|---|---|---|
| 元数据扫描 | `scripts/audit_system_inventory.py` | PASS | `inventory/*.json/csv` |
| 细分统计 | `scripts/audit_inventory_supplement.py` | PASS | `inventory/supplement.json/md` |
| 文档生成 | `scripts/audit_generate_docs.py` | PASS | `04`、`05` |
| UI 探针（50 页） | `scripts/audit_ui_probe.py` | 50/50 HTTP 200 | `inventory/ui_probe.json/md` |
| 三端冒烟（71 页） | `scripts/product_smoke.py` | PASS | 产品融合报告 §7 |
| Chromium 验收（27 项） | `scripts/product_e2e.py` | PASS | 17 张截图 |
| 角色授予生效（8 项） | `scripts/product_grant_check.py` | PASS | `grant_check.json` |
| 跨端状态一致（8 项） | `scripts/product_consistency.py` | PASS | `consistency.json` |

> 以上脚本输出位于 `.local/evidence/product/`（不入库），
> 正式文档只引用结论与命令，不复制 `.local` 内容。

---

## 4. 迁移与正式库证据（B）

| 项 | 结果 | 证据 |
|---|---|---|
| 迁移预览 | 源 3 学生/2 教师/1 管理员等 | `.local/evidence/migration/preview.json` |
| 迁移执行 | 6 账号/3 学籍/8 单元/4 关系 | `apply.json` |
| 迁移校验 | 全部角色/学籍/权限检查 PASS | `verify.json` |
| 回滚 | 删 3 学籍/6 账号/8 单元 | `rollback.json` |
| 再迁移 | 再次 PASS | `apply.json`（第二次） |
| 正式库只读 | 指纹 `b914b39c…` 前后一致 | `product/formal_db_fingerprint.json` |

---

## 5. 按模块的证据映射

| 模块 | 主要证据 |
|---|---|
| M1 工作台 | A：产品层 4 类；C：截图 01/05/11 |
| M2 身份权限 | A：r21 110 例、产品层 9 例；B：grant_check 8 项 |
| M3 组织 | A：R4 72 例；B：探针 |
| M4 学籍 | A：R4/R12 115 例、产品层 4 例；B：迁移 |
| M5 教师 | A：R5 56 例；B：探针（档案 CRUD 缺失见 08） |
| M6 教务 | A：R5 56 例、产品层建课；B：探针 |
| M7 选课 | A：R5；D：产品只读 |
| M8 排课 | A：R11 40 例；C：课表截图 |
| M9 考勤 | A：R13 41 例、产品层审批；C：截图 03/08 |
| M10 工作流 | A：R6 47 例；B：探针 |
| M11 寝室 | B：探针；D：代码 |
| M12 活动 | A：R14 28 例、产品层报名；C：E2E 建活动 |
| M13 社团 | A：R15 28 例；B：探针 |
| M14 场地 | A：R16 59 例、产品层建场地；C：截图 18 |
| M15 论坛公告 | A：R17 32 例、产品层公告；C：截图 14 |
| M16 财务 | A：R18 34 例；B：探针 |
| M17 党建 | A：R19 35 例；**C 缺**（产品无入口） |
| M18 数据交换 | A：S25 85 例；B：探针 |
| M19 分析 | A：R7 31 例；B：探针 |
| M20 通知 | A：R6、产品层；B：探针 |
| M21 运维 | A：R9（含在 operations 425）；B：截图 11/13 |
| M22 安全 | A：S16/S09/S10/S11/S13/S15 共 148 例；**C 缺**（产品未接入） |
| M23 app01 | A：app01 188 例；D：代码对照 |

---

## 6. 明确"未验证"的项

以下项目本轮**没有**产品路径的运行证据，标记为未验证，不推断为可用：

| 项 | 原因 | 状态 |
|---|---|---|
| `/api/` 开放接口在产品配置下的行为 | 无产品界面与联调 | IMPLEMENTED_NOT_VERIFIED |
| 党建专项（`/r19/`）产品内可用性 | 产品无入口，未做浏览器验证 | IMPLEMENTED_NOT_VERIFIED |
| MFA/step-up/双人审批/策略/隐私/上传安全 | 产品配置未注册 | IMPLEMENTED_NOT_VERIFIED |
| 论坛/举报（`/r17/`）产品内可用性 | 无产品入口 | IMPLEMENTED_NOT_VERIFIED |
| 流程实例发起/流转（`/r6/`） | 无产品入口 | IMPLEMENTED_NOT_VERIFIED |
| 学生签到/补签/销假/退费/退社/活动签到 | 无产品入口 | IMPLEMENTED_NOT_VERIFIED |
| 组织 CRUD、教师档案 CRUD、社团审批 | 无产品入口 | IMPLEMENTED_NOT_VERIFIED |
| 排课求解（`/r11/plan/`）在 `settings_product` 下 | 仅独立 R11 测试与产品读取验证 | IMPLEMENTED_NOT_VERIFIED（产品内求解） |
| WCAG 自动扫描 | 产品配置未接入 `smass_a11y` | NOT_VERIFIED |

---

## 7. 证据可信度说明

- **A 级**证据可直接复现，命令与 settings 均已给出；
- **B 级**证据依赖本机数据库（`smass_product_dev`），重建后数值会变，
  但脚本可重跑；
- **C 级**截图位于 `.local/evidence/product/screenshots/`（不入库），
  文档只描述结论；
- **D 级**仅代码阅读，已在对应条目标注"未验证"。
