# SMASS PMR Change Log（PM0–PM10）

基线：`ac238df`　分支：`feat/smass-r4-r10-integrated-platform`

## 1. 提交序列

| SHA | 类型 | 内容 |
|---|---|---|
| `55524db` | feat | PM0 基线审计 + PM1 旧密码兼容（29 例） |
| `7ce65e0` | feat | PM2 合成数据集生成器（19 例 + 四规模） |
| `ecf811b` | feat | PM3 行迁移与严格对账（15 例） |
| `3e0384f` | feat | PM4 双写与批次回滚（7 例） |
| `31c1f82` | feat | PM5 完整升级、故障注入与恢复（13 例） |
| `1e833dc` | feat | PM6+PM7 性能、锁测量与多进程并发（13 例） |
| `b915fdf` | feat | PM8 安全、会话与可访问性回归（23 例） |
| 本提交 | feat | PM9 授权包 + PM10 最终证据与判定 |

## 2. 新增脚本

| 脚本 | 作用 |
|---|---|
| `scripts/pmr_gate.py` | 四层门禁：结构 / 证据 / 产物 / **命令日志退出码** |
| `scripts/pmr_synthetic_fixture.py` | 合成旧库生成（四规模，确定性，无 PII） |
| `scripts/pmr_migrate_rows.py` | 行迁移 + 幂等映射表 + 严格对账 |
| `scripts/pmr_dual_write.py` | 双写（off/dual/r10）+ 失败注入补偿 + 批次回滚 |
| `scripts/pmr_upgrade_restore.py` | 带数据升级 + 三故障注入 + 备份恢复 |
| `scripts/pmr_bench.py` | 多规模查询延迟 + 锁/连接指标 + 真实多进程 |

## 3. 新增配置

| 文件 | 作用 |
|---|---|
| `smass/settings_pmr.py` | PMR 演练库（`target_` / `upg_` / `restore_` 三前缀放行） |

## 4. 新增测试

| 文件 | 例数 | 覆盖 |
|---|---|---|
| `test_pmr_pm1_legacy_auth.py` | 29 | 格式识别 / 单次双重 MD5 / 懒惰升级 / 拒绝路径 / 限速 / 密钥泄漏固化 |
| `test_pmr_pm2_fixture.py` | 19 | 编码三格式 / 合成格式非真实 / 权重和为 1 / 守卫 / 对抗用例 |
| `test_pmr_pm3_migration.py` | 15 | 可用哈希判定 / 前缀守卫 / 映射表唯一键 / 计数封顶 |
| `test_pmr_pm4_dual_write.py` | 7 | 三模式常量 / 幂等键唯一 / 批次索引 / flags 独立 |
| `test_pmr_pm5_upgrade_restore.py` | 13 | 前缀契约 / HashCarrier / 双指纹确定性与"插一行必变" / 故障点存在 |
| `test_pmr_pm6_bench.py` | 13 | 百分位边界 / 主机画像 / SHOW 取值 / 多进程契约 / 隔离级别记录 |
| `test_pmr_pm8_security.py` | 23 | 陈旧 session / 强制改密 / 停用 / CSRF / 审计载荷 / scope 一致 |

**合计新增 119 例。**

## 5. 新增文档

| 文档 | 内容 |
|---|---|
| `SMASS_PMR_Legacy_Auth_Compatibility.md` | 格式映射表（源码依据）+ 验证结果 + 密钥泄漏风险 |
| `SMASS_PMR_Synthetic_Data_Spec.md` | 无 PII 保证 + 四规模实测 + 两个指纹定义 |
| `SMASS_PMR_Row_Migration_and_Reconciliation.md` | 映射关系 + 幂等 + 五类计数 + 6 项对账 |
| `SMASS_PMR_Dual_Write_Rollback.md` | 三模式 + 失败注入补偿 + 批次回滚 |
| `SMASS_PMR_Upgrade_Restore_Drill.md` | 带数据升级 + 三故障点 + 双指纹恢复验证 |
| `SMASS_PMR_Performance_and_Concurrency.md` | 1k/10k 实测 + 多进程 PID 证据 |
| `SMASS_PMR_Security_and_A11y.md` | 陈旧 session + 审计载荷 + scope 一致 |
| `SMASS_PMR_Real_Data_Authorization_Package.md` | 授权申请（**未执行**） |
| `SMASS_PMR_Test_Report.md` | 实测测试总数 |
| `SMASS_PMR_Change_Log.md` | 本文件 |
| `SMASS_PMR_Executive_Report.md` | 执行摘要 |
| `SMASS_PMR_Go_NoGo.md` | 三类判定 |

## 6. 修复的真实缺陷（按发现顺序）

| # | 缺陷 | 发现于 | 性质 |
|---|---|---|---|
| 1 | 合成指纹含 PBKDF2 随机 salt → 同 seed 不可复现 | PM2 | 设计缺陷 |
| 2 | 重复主键用 `try/except IntegrityError` 捕获失效 | PM2 | 实现缺陷 |
| 3 | 班级父级用 `major_id` 查 `college_map`，永远查不到 | PM3 | **逻辑错误**（连累 10 个学生档案） |
| 4 | 对账断言用本轮计数而非源数据基准 | PM3 | 断言错误 |
| 5 | `app01_admin.id` 是 `varchar(3)`，用了 7 字符 id | PM4 | **schema 契约违反** |
| 6 | 登录抽样用 SQL 过滤后的位置当 index | PM5 | **逻辑错误**（1k 只 1/4 通过） |
| 7 | `settings_pmr` 未放行 `restore_` 前缀 | PM5 | 配置遗漏 |
| 8 | `SHOW ... LIKE` 取到变量名而非值 | PM6 | 实现缺陷 |
| 9 | 自造指标 `students_scoped_bench` 无计算实现 | PM6 | 误用 API |
| 10 | 测试断言把公开页 `/r10/` 当作需登录 | PM8 | **断言错误**（产品无缺陷） |

**其中 3 个是"测试写错了"，不是产品缺陷**——第 4、6、10 条。
报告里如实区分，不把测试自己的 bug 计成产品改进。

## 7. 修改的既有文件

| 文件 | 变更 |
|---|---|
| `smass/settings_pmr.py` | 新增；后续放宽到三前缀（PM5） |
| `scripts/pmr_migrate_rows.py` | 新增 `migrate_majors` 层（PM3 修复） |
| `scripts/pmr_synthetic_fixture.py` | 指纹定义改版；重复主键改先查后插 |
| `scripts/pmr_upgrade_restore.py` | 登录验证改 legacy 侧；index 从 id 反推 |

**未修改**：`smass` 数据库、`AUTH_USER_MODEL`、`app01` 应用代码、MySQL 全局配置。

## 8. 决策记录（PMD-001 至 PMD-027）

27 条，全部在 `docs/dsh_run/PMR_DECISIONS.md`。分类：

| 类别 | 条目 |
|---|---|
| 旧密码与密钥 | PMD-001..005, 025 |
| 合成数据 | PMD-006..008 |
| 迁移逻辑 | PMD-009..013, 017 |
| 双写与补偿 | PMD-014..016 |
| 升级与恢复 | PMD-018..020 |
| 性能与并发 | PMD-021..024 |
| 安全与断言纪律 | PMD-026..027 |

## 9. 测试数变化

| 阶段 | 总数 |
|---|---|
| H0–H9 完成（`ac238df`） | 811 |
| PM 阶段新增 | **+119** |
| PM 完成后实测 | 见 `SMASS_PMR_Test_Report.md` |
