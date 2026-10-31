# 09 测试与回滚报告

> 本轮所有验证的实际命令与结果。证据位于 `.local/evidence/unify/`。
> 全量回归结果见 §10（本轮实测）。

---

## 1. 测试矩阵

| # | 测试 | 命令 | 结果 |
|---|---|---|---|
| 1 | 验证库建库+迁移 | `db_unify.py init` | PASS（127 表） |
| 2 | 结构/主键/外键/唯一约束 | `db_unify.py verify` | PASS |
| 3 | 种子/基础字典 | `db_unify.py seed` | PASS |
| 4 | 账号迁移与身份映射 | `legacy_migration.py --verify` | PASS |
| 5 | 数据对账 | `db_unify_reconcile.py` | PASS（13 项） |
| 6 | 回滚 → 再迁移 → 再校验 | `--rollback` / `--apply` / `--verify` | PASS |
| 7 | 断库运行 | `db_unify_detached_test.py` | PASS（13 页） |
| 8 | 运行时旧库依赖 | `db_unify_dependency_scan.py` | PASS（0） |
| 9 | 产品层回归 | `manage.py test smass_workspace --settings=smass.settings_product` | PASS（40） |
| 10 | 全量回归 | `r10_full_regression.py --json` | 见 §10 |
| 11 | 正式库只读指纹 | `db_fingerprint.py` | 见 §11 |
| 12 | Git 准入 | `repo_admission_check.py` | PASS |
| 13 | 默认启动配置 | `manage.py shell -c ...` | `settings_product` / `smass_product_dev` / `urls_product` |

---

## 2. 验证库结构

- 127 表，全部有主键；
- 外键约束 > 0、唯一约束 > 0；
- 无未应用迁移；
- 角色组 4 个；
- 账号/学号唯一；
- 学生/教师档案 1:1。

证据：`verify.json`、`init.json`。

---

## 3. 账号迁移与权限

| 用例 | 结果 |
|---|---|
| 学生访问 `/admin/` | 403 |
| 学生访问 `/student/` | 200 |
| 教师访问 `/admin/` | 403 |
| 管理员访问 `/admin/` | 200 |
| 角色/学籍/档案绑定 | 全部通过 |

证据：`migration_verify.json`。

---

## 4. 对账

13 项全部 PASS（账号 3/2/1、学籍 3、档案 3/2、组织 12、任职 4、
住宿 0=0、密码继承、PII 掩码、身份证 0）。
证据：`reconcile.json`。

---

## 5. 回滚与再迁移

| 步骤 | 结果 |
|---|---|
| `--rollback` | 删除 3 学籍 / 6 账号 / 8 单元（仅本批次无引用） |
| `--apply`（再次） | 成功，无重复账号 |
| `--verify` | PASS |
| 源库指纹 | 前后一致 |

证据：`rollback.json`、`reapply.json`、`reverify.json`。

---

## 6. 断库运行

重命名 16 张 app01 旧业务表后：

| 角色 | 页面 | 结果 |
|---|---|---|
| uni_student | 工作台/学籍/寝室/考勤/课表 | 200 |
| uni_teacher | 工作台/学生/考勤 | 200 |
| uni_admin | 总览/学籍/用户/组织/系统配置 | 200 |
| 登录 | 三角色 | 302 落地正确 |

失败 0。证据：`detached.json`。

---

## 7. 运行时依赖

| 类别 | 数量 |
|---|---|
| runtime | 0 |
| app01_internal | 3 |
| legacy_compat | 16 |
| migration_tool | 126 |
| test | 35 |

`compat_imported_by_runtime=[]`；`audit_dependency_only` 为
`smass_organization/services.py`、`export.py`（只写审计，不读旧表）。

---

## 8. 产品层与浏览器

| 项 | 结果 |
|---|---|
| `smass_workspace` 40 例 | OK |
| 产品 Chromium 27 项（基线 `80c8d85`） | PASS |
| 越权 403（产品层 9 项 + E2E 4 项） | PASS |
| 跨端一致性 8 项 | PASS |

> 说明：浏览器 E2E 针对产品库 `smass_product_dev`；
> 验证库通过 Django 客户端完成断库页面验证（无浏览器）。

---

## 9. 默认启动与旧配置

| 命令 | 结果 |
|---|---|
| `python manage.py check` | 产品配置 PASS |
| `manage.py` 默认 | `settings_product` / `smass_product_dev` / `urls_product` |
| `test app01 --settings=smass.settings` | 188 例 OK |
| `test tests_e2e --settings=smass.settings` | 16 例 OK |

---

## 10. 全量回归（本轮实测）

命令：`python scripts/r10_full_regression.py --json`

结果：**32 套件 / 1800 例 / 0 失败**（见 `.local/evidence/unify/regression.log`）。

| 套件 | 用例 | 结果 |
|---|---|---|
| smass_operations | 425 | PASS |
| smass_analytics | 31 | PASS |
| smass_organization | 72 | PASS |
| smass_data_exchange（roundtrip+ui） | 60 | PASS |
| smass_data_exchange（r5） | 25 | PASS |
| smass_academic | 56 | PASS |
| smass_facilities | 59 | PASS |
| smass_scheduling | 40 | PASS |
| smass_workflow | 47 | PASS |
| smass_api | 23 | PASS |
| r22_account | 117 | PASS |
| r21_account | 110 | PASS |
| app01（显式 legacy settings） | 188 | PASS |
| tests_e2e（显式 legacy settings） | 16 | PASS |
| smass_enrollment | 43 | PASS |
| smass_attendance | 41 | PASS |
| smass_activities | 28 | PASS |
| smass_clubs | 28 | PASS |
| smass_forum | 32 | PASS |
| smass_finance | 34 | PASS |
| smass_party | 35 | PASS |
| smass_portal | 36 | PASS |
| smass_uploads | 27 | PASS |
| smass_audit | 20 | PASS |
| smass_security_tests | 20 | PASS |
| smass_mfa | 24 | PASS |
| smass_stepup | 26 | PASS |
| smass_policy | 25 | PASS |
| smass_privacy | 25 | PASS |
| smass_api_security | 28 | PASS |
| smass_a11y | 19 | PASS |
| smass_workspace | 40 | PASS |

---

## 11. 正式库只读指纹

正式库使用两套独立指纹算法，分别覆盖"迁移期"与"回归期"：

| 算法 | 计算内容 | 时点 | 值 |
|---|---|---|---|
| `legacy_migration.source_fingerprint` | 26 表名 + 行数 + 列定义 | 迁移/断库/回滚/再迁移前后 | `940a687d84c8b8a35b7295a359aef18e160403ae25736d7844dbcb16d352455c` |
| `scripts/db_fingerprint.py` | schema / tables / rows 分项哈希 | 全量回归前后 | `b914b39cc7ec9469b1ac925dfa526d4f8c58bd9283fcfdad0a834bedaee106e3` |

两套指纹在各自前后时点**完全一致**；26 表 / 111 列未变；未执行任何写入。

---

## 12. Git 准入

`repo_admission_check.py`：索引与暂存区扫描 0 问题，PASS。

---

## 13. 失败与例外

| 项 | 说明 | 处理 |
|---|---|---|
| 首次 `seed` 失败 | `TeacherProfile.teacher_no` 超过 7 字符 | 改为 `UNIT001` 后 PASS |
| 首次 `db_unify init` 失败 | 脚本未把 ROOT 加入 sys.path | 修复后 PASS |
| 首次迁移到验证库失败 | `global SETTINGS` 声明位置错误 | 修复后 PASS |
| 全量回归历史偶发 | 基线曾出现 `smass_api_security` 1 例偶发 | 本轮 0 失败；脚本已保留失败尾部输出 |

---

## 14. 结论

- 结构、约束、身份、对账、回滚、断库、默认启动、产品层、全量回归、
  指纹、准入全部 PASS；
- 未发现阻断性问题；
- 退役治理条件（加密备份、舍弃审批、正式授权）仍未满足，见 `10`。
