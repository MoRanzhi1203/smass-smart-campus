# 11 旧库退役与新版数据库正式化

> 基线：Git `05917d7` → 本轮提交
> 用户决定：原 `smass` 库中数据全部为测试数据，无保留价值，可全部舍弃。
> 本轮目标：新库成为唯一权威，旧库逻辑退役；物理删除需针对 `smass` 的明确授权。
> 证据：`.local/evidence/retire/`

---

## 1. P0 旧库删除前核验（只读）

### 1.1 实例与对象

| 项 | 实测 |
|---|---|
| MySQL | 8.0.18，主机 `MSI`，端口 3306 |
| 目标库 | `smass` |
| 连接账号 | `root@localhost` |
| 对象总数 | 26（全部为表） |
| 视图 / 触发器 / 事件 / 存储过程 | 0 / 0 / 0 / 0 |
| 总行数 | 155 |
| 跨库引用（其它库视图/例程引用 smass） | 0 |
| 其它活动连接（排除核验自身） | 0 |
| 表/列 | 26 表 / 111 列（`db_fingerprint`） |

### 1.2 数据性质核验

| 检查 | 结果 | 判定 |
|---|---|---|
| 身份证号（学生 3 + 教师 2） | 5 个存在，**校验位有效 0 个** | 合成/测试数据 |
| 手机号 | 非测试号段 0 个 | 合成/测试数据 |
| 行数规模 | 155 行（学生 3、教师 2、管理员 1…） | 测试规模 |
| 真实业务记录（账单/考勤/成绩等） | 不存在对应表 | 无 |

**结论**：与用户"全部为测试数据"的前提一致；未发现真实个人信息或真实业务记录。
核验脚本：`scripts/legacy_retire_verify.py`，结果 `p0_verify.json`，`verdict=DELETION_SAFE`。

### 1.3 配置与进程依赖

| 类别 | 发现 | 处置 |
|---|---|---|
| 产品运行配置 | `settings_product` 连接 `smass_product_dev`，不连 `smass` | 无需改动 |
| `.env.example` | 原默认 `DB_NAME=smass` | **已改为 `smass_product_dev`**，并注明历史库仅供迁移 |
| 旧脚本（`db_backup.ps1`/`db_restore_drill.ps1`/`charset_drill.ps1`） | 默认参数 `smass` | 标记 TEST_ONLY/ARCHIVE；不参与产品启动 |
| 旧 settings（`settings_demo/h5/pmr/integrated_dev`） | 测试库名含 `smass` | ARCHIVE；产品不使用 |
| 迁移/审计脚本 | 显式读取 `smass` | TEST_ONLY（只读） |
| 活动连接 | 0 | — |

---

## 2. 精确删除计划（未执行）

```sql
-- 仅在取得针对数据库 `smass` 的明确物理删除授权后执行
-- 执行前再次运行 legacy_retire_verify.py，确认 verdict=DELETION_SAFE
DROP DATABASE `smass`;
```

| 项 | 内容 |
|---|---|
| 删除对象 | 仅数据库 `smass`（26 表 / 0 视图 / 0 触发器 / 0 事件 / 0 例程） |
| 不包含 | MySQL 实例、其他数据库、Git 历史、备份文件、`.env` |
| 前置条件 | ① 明确授权删除 `smass`；② 核验清单一致；③ 无活动连接/跨库引用；④ 无程序配置引用；⑤ 备份或确认无需备份 |
| 回退 | 无（不可逆）；如需恢复只能从独立备份 |

**本轮未执行 DROP**：用户"数据可舍弃"是数据层面授权，不等于对数据库对象的
物理删除授权；按 P5 要求停在 `LOGICALLY_RETIRED`。

---

## 3. 旧系统依赖分类

| 组件 | 分类 | 依据/处置 |
|---|---|---|
| `app01` 安全状态表（`AccountSecurityState`） | **ACTIVE** | 密码生命周期/会话世代中间件使用 |
| `app01.LoginDevice` | **ACTIVE** | 会话/设备管理 |
| `app01.middleware.*` | **ACTIVE** | 隐私响应/密码生命周期/会话安全 |
| `app01` 旧业务模型（Student/Teacher/Admin/Classes/College/Major/Grade/Department/Building/Dormitory/Nation/Position…） | **ARCHIVE** | 产品运行零引用；仅迁移/兼容测试使用 |
| `app01` 旧视图/旧后台模板 | **ARCHIVE** | 未挂载产品 URL |
| `smass/settings.py` + `smass/urls.py`（旧入口） | **TEST_ONLY** | 仅 app01 188 例回归显式使用 |
| `app01/management/commands/seed_dev.py` | **TEST_ONLY** | 旧开发数据生成；产品不用 |
| `smass_migrate` / `legacy_migration.py` 迁移桥接 | **ARCHIVE（历史工具）** | 不再作为新项目启动流程 |
| `r22_account` 双身份/双写 | **ARCHIVE** | 产品零调用；`audit` 仅写审计表 |
| `r22_account.dual_write` | **RETIRE** | 产品未注册中间件、无调用 |
| 旧 `settings_demo/h5/pmr/r4–r22/s*` | **TEST_ONLY/ARCHIVE** | 独立测试与历史追溯 |
| `scripts/db_backup.ps1` / `db_restore_drill.ps1` / `charset_drill.ps1` | **ARCHIVE** | 默认指向旧库；不参与产品 |
| `scripts/db_verify.py` / `s22`/`s23` 演练脚本 | **TEST_ONLY** | 显式引用旧库，只读 |
| `templates/admin|student|teacher|layout|login`（旧） | **ARCHIVE** | 产品不使用 |
| `.env.example` 的 `DB_NAME=smass` | **REMOVE_CANDIDATE** | 已改为 `smass_product_dev` |
| 旧库本身 | **LOGICALLY_RETIRED** | 待物理删除授权 |

> 未删除 `app01`：安全状态表与中间件是产品运行必需；旧业务表删除会破坏
> 188 例 app01 回归与历史追溯。分类优先于删除。

---

## 4. 新版数据库唯一权威

| 项 | 值 |
|---|---|
| 权威库 | **`smass_product_dev`**（保留现有名称，避免改名误连接） |
| 迁移 | 127 表；`migrate` 从零可执行 |
| 初始化 | `scripts/product_bootstrap.py`（演示/开发）或 `db_unify.py init/seed`（验证） |
| 基础配置 | 角色组、组织字典、默认学期课程可重复初始化 |
| 演示数据 | 仅开发/演示环境生成；正式环境不自动生成假数据 |
| 幂等 | `db_unify seed` 连续执行两次结果一致；`product_bootstrap` 幂等 |
| 旧表依赖 | 0（`db_unify_dependency_scan.py`） |
| 旧库存在性 | 不再是运行前提（断库验证通过） |

### 4.1 从零初始化复验（本轮）

| 步骤 | 结果 |
|---|---|
| `db_unify.py init`（DROP/CREATE + 127 表迁移） | PASS |
| `db_unify.py seed`（第一次） | PASS |
| `db_unify.py seed`（第二次，幂等） | PASS，数量不变 |
| `db_unify.py verify` | PASS |
| `legacy_migration --apply`（可选，历史数据演练） | PASS（本任务不再需要） |

### 4.2 环境布局建议

| 环境 | 库名 | 状态 |
|---|---|---|
| 开发 | `smass_product_dev` | 现状，保留 |
| 测试 | `test_smass_product_dev`（Django 自动） | 现状 |
| 验收 | `smass_unified_verify` | 现状，可随时重建 |
| 生产 | 待上线授权后单独配置 | 未启用 |

> 未改名：现有 `settings_product` 与脚本均校验 `smass_product_dev` 前缀，
> 改名需同步修改守卫，收益低、风险高。

---

## 5. P3 断库全业务验证

脚本 `scripts/product_detached_full_test.py`：
在 `smass_product_dev` 临时重命名 16 张 app01 旧业务表，五类账号执行全业务。

| 项 | 结果 |
|---|---|
| 页面 | **63 个页面全部 200/302**（学生 15、教师 10、辅导员 4、学院管理员 3、超管 22、共用 3） |
| 写操作 | 8/8 PASS：请假创建 → 教师审批 → 学生端同步；公告创建 → 学生可见；活动创建 → 学生报名；场地预约 → 管理员审批 |
| 持久化 | 每项写操作均回查数据库确认 |
| 旧表恢复 | `finally` 恢复，产品库结构复原 |

**本轮发现并修复的真实缺陷**：`smass_workspace/views/student.py` 中
`from smass_facilities.services import BookingError`（实际类名为 `FacilityError`），
导致学生提交场地预约 500。已修复并新增 2 例产品层测试（预约创建/取消），
测试由 40 例增至 42 例。

---

## 6. 退役状态

| 状态 | 是否达成 | 说明 |
|---|---|---|
| `RETIREMENT_PREPARED` | ✅ | 可舍弃性核验、对象清点、连接迁出、依赖扫描、新库初始化、全业务回归、删除计划、审计记录齐备 |
| `LOGICALLY_RETIRED` | ✅ | 产品/测试运行不依赖旧库；旧库不再提供业务服务；新库为唯一权威；旧库隔离待删 |
| `PHYSICALLY_REMOVED` | ❌ **未执行** | 缺少针对 `smass` 的明确物理删除授权与数据库级备份确认 |

### 6.1 逻辑退役的具体动作

1. 产品配置连接 `smass_product_dev`；`settings_product` 链不引用 `smass`；
2. 默认 `manage.py` 进入产品配置；
3. `.env.example` 默认库改为 `smass_product_dev`；
4. 运行时旧表依赖 0；断库全业务 PASS；
5. 迁移工具标记为历史工具，不再作为启动流程；
6. 旧库保持原样、只读、无活动连接。

### 6.2 物理删除剩余条件

| 条件 | 状态 |
|---|---|
| 针对数据库 `smass` 的明确物理删除授权 | ❌ 未取得（"数据可舍弃"不等于"授权 DROP DATABASE"） |
| 删除对象与核验清单一致 | ✅ 26 表/0 视图/0 触发器/0 事件/0 例程 |
| 无程序使用 | ✅ 活动连接 0、跨库引用 0、产品配置 0 |
| 不影响其他数据库 | ✅ 仅 `smass` |
| 数据库级备份（或确认无需） | ⚠️ 仅有 Git 备份；测试数据可舍弃，建议仍保留一次结构快照 |
| 退役审计记录 | ✅ 本文档 + `p0_verify.json` |

**下一步（需你一句话授权）**：

> “授权删除数据库 `smass`”

授权后执行：再次核验 → 结构快照（`mysqldump --no-data`，不含行数据）→
`DROP DATABASE \`smass\`` → 复核实例内其余库未受影响 → 记录审计。

---

## 7. 最终验收对照

| # | 要求 | 结果 |
|---|---|---|
| 1 | 新库实际名称 | `smass_product_dev` |
| 2 | 完整数据库结构 | 127 表（`db_unify verify` + 迁移图） |
| 3 | 从零初始化命令与证据 | `db_unify.py init/seed/verify`，`fresh_*.json` |
| 4 | 旧库运行时依赖扫描 | 0（`db_unify_dependency_scan.py`） |
| 5 | 三端断库验证 | 63 页 + 8 写操作 PASS（`p3_detached.json`） |
| 6 | 完整回归 | 见 `09` / 本轮回归日志（代码修复后复跑） |
| 7 | 旧系统停用与清理 | 分类表见 §3；`.env.example` 已改；默认启动已改 |
| 8 | 退役状态 | `LOGICALLY_RETIRED` |
| 9 | 未物理删除的原因 | 缺少针对 `smass` 的明确删除授权（见 §6.2） |
| 10 | Git 与工作区 | 本轮提交见最终回复；工作区干净 |
