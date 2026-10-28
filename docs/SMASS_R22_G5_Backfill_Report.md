# SMASS R2.2 G5 回填演练报告（Backfill Report）

- 阶段：G5（隔离回填演练，**未触碰正式库写入**）
- 源库：`smass`（**只读**，26 表 / Admin 1 · Student 3 · Teacher 2）
- 目标库：`smass_r22_g5_stage`（本轮新建，不存在才创建）
- 脚本：`scripts/r22_g5_ro_user.py`、`scripts/r22_g5_stage.py`、`scripts/r22_g5_drill.py`
- 配置：`smass/settings_r22_g5.py`

## 1. 源保护（数据库级只读，不是应用层检查）

创建专用账号 `smass_g5_ro`，**仅** `GRANT SELECT ON smass.*`（不修改任何既有授权）。

实测写探测：

| 探测 | 结果 |
|---|---|
| `SELECT` | 成功 |
| `UPDATE` | **被数据库拒绝**（OperationalError） |
| `INSERT` | **被拒绝** |
| `DELETE` | **被拒绝** |
| `CREATE TABLE` | **被拒绝** |

凭据写入 `%TEMP%\smass_g5_ro_credential.txt`，**不在仓库**；脚本已改为从 `SMASS_DB_PASSWORD` 环境变量读取管理员口令，无硬编码。

## 2. 一致性快照

| 项 | 值 |
|---|---|
| 方法 | `mysqldump --single-transaction`（只读账号） |
| 耗时 | 1.02 s |
| 大小 | 33,733 bytes |
| 位置 | 系统临时目录（**未进 Git**） |
| 源 schema 指纹（前后） | `4caf932e82f3a0564e9d5722d64a01dd`（**一致**） |
| 源计数（前后） | 1 / 3 / 2（**一致**） |
| stage 计数 | 1 / 3 / 2（匹配） |
| stage schema 指纹 | 与源相同 |

## 3. 回填结果

| 阶段 | 输出 |
|---|---|
| `--dry-run` | `processed=6 created=6 skipped=0 conflicts=0 errors=0` |
| 实跑 | `accounts=6 roles=6 links=6 student_profile=3 teacher_profile=2` |
| 幂等重跑 | `created=0 skipped=6` |

契约核对：

| 检查 | 结果 |
|---|---|
| 6 条来源 → 6 条 `LegacyAccountLink` | PASS（一对一，无重复） |
| 角色语义 | admin→system_admin / teacher→teacher / student→student |
| Profile 关联 | 3 学生 + 2 教师 |
| 启用状态 | 全部 `is_active=True`，无 `deactivated_at` |
| 密码哈希 | **原样搬迁**（逐条与旧表比对相等，只输出计数不输出哈希） |
| `must_change_password` | 全部为 True（旧哈希来源，要求首次改密） |

## 4. 关于跨库原子性（计划要求调查）

`backfill_accounts_r21` **只操作单一数据库连接**：源表 `app01_*` 与新表 `r21_account_*` 都在同一个 stage 库内。
因此 `transaction.atomic()` 的单行回滚在**同一连接**内成立，不存在"跨库无原子性"问题。

G5 的做法是"克隆到同一库再回填"，而不是"两个库之间双写"——后者才需要补偿事务。

## 5. 未做

| 项 | 状态 |
|---|---|
| 正式库回填 | **NOT DONE**（未授权） |
| 大数据量回填 | NOT RUN（仅 6 行样本） |
| 并发回填 | NOT RUN |
