# 11 旧库退役（逻辑退役）

> **本轮只做逻辑退役。物理删除 `smass_product_dev` / `smass_simulation` /
> `smass_unified_verify` 需要你针对这三个具体库的明确授权，本次未执行任何 DROP。**

---

## 1. 退役审计（`scripts/v22_retire_audit.py`，只读）

| 数据库 | 存在 | 表数 | 状态 |
|---|---|---|---|
| `smass_product_dev` | 是 | 141 | **LOGICALLY_RETIRED** |
| `smass_simulation` | 是 | 143 | **LOGICALLY_RETIRED** |
| `smass_unified_verify` | 是 | 127 | **LOGICALLY_RETIRED** |
| `smass_campus`（唯一业务库） | 是 | 143 | ACTIVE |

- **活动连接**：`information_schema.processlist` 中 DB 命中三库的连接数为 **0**；
- 审计报告：`.local/evidence/v22/retire_audit.json`。

## 2. 引用清单

| 类别 | 是否引用旧库 | 说明 |
|---|---|---|
| `manage.py` 默认 | 否 | 指向 `settings_campus` |
| `settings_campus.py` | 否 | 只连 `smass_campus` |
| 8050 运行服务 | 否 | 实测 `DB = smass_campus` |
| 业务代码（`smass_workspace`/业务 app） | 否 | 无硬编码库名 |
| 测试 | 否 | 使用 `test_smass_campus` |
| `.env.example` / README | 否 | 指向 `smass_campus` |
| 历史档案（显式指定才会用） | 是 | `settings_product.py`、`settings_simulation.py`、`settings_unified_verify.py`、`scripts/db_unify*.py`、`scripts/legacy_*.py`、`scripts/product_*.py`、V2.0/V2.1 文档 |

> 结论：**运行时零依赖旧库**；引用仅存在于“需显式 `--settings` 才会加载”的档案与历史文档中。

## 3. 备份（物理删除前置条件）

| 项 | 结果 |
|---|---|
| 工具 | `mysqldump`（已检测存在） |
| 命令 | `mysqldump --single-transaction --quick --routines smass_campus` |
| 产物 | `.local/backup/smass_campus_20261101_213326.sql`（35.0 MB，5.4 s） |
| 恢复方式 | `mysql smass_campus < 备份文件`（新库需先创建同字符集） |

## 4. 物理删除的影响与边界（未执行）

若后续获得授权，影响范围仅限：

| 删除对象 | 影响 |
|---|---|
| `smass_product_dev` | 丢失 V2.0/V2.1 产品演示库（7 学籍/5 教师/旧演示数据）；`dev_admin` 已在 campus 保留 |
| `smass_simulation` | 丢失 large 仿真库原件；campus 已等价重建（同 seed），旧库仅作对照 |
| `smass_unified_verify` | 丢失 V2.0 统一迁移验证证据（结构落后） |

**不会**删除：`smass_campus`、MySQL 实例、其他项目库（`agri_db`/`school`/`smass_pmr_*` 等）、Git 历史、`.local/backup` 备份文件。

## 5. 删除步骤（待授权后执行）

```powershell
# 1) 复核
python scripts/v22_retire_audit.py            # 确认活动连接 0、campus 正常
# 2) 断开任何显式配置的使用（停止使用旧 settings 的服务）
# 3) 物理删除（需用户书面授权这三个库名）
mysql -e "DROP DATABASE smass_product_dev;"
mysql -e "DROP DATABASE smass_simulation;"
mysql -e "DROP DATABASE smass_unified_verify;"
# 4) 再次审计：三库 ABSENT，campus ACTIVE
python scripts/v22_retire_audit.py
```

## 6. 当前状态

**未物理删除**；三库仍占用磁盘（141 + 143 + 127 张表）。这与任务书“不得提前宣称已删除”一致。
