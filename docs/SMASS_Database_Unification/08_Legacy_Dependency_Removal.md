# 08 旧库依赖移除

> 目标：产品运行链路不再读写 app01 旧业务表。
> 方法：静态引用扫描 + 运行时 import 图 + 断库运行测试 + 默认启动改造。
> 证据：`scripts/db_unify_dependency_scan.py`、`.local/evidence/unify/dependency_scan.json`、
> `detached.json`。

---

## 1. 扫描结果（实测）

| 类别 | 数量 | 说明 |
|---|---|---|
| 运行时依赖 | **0** | 产品代码未引用 app01 旧业务表 |
| `app01` 内部引用 | 3 | app01 自身模块（forms/services/views） |
| `r22_account` 兼容层 | 16 | 表名映射常量与双身份代码 |
| 迁移工具 | 126 | `scripts/`（一次性迁移/演练） |
| 测试 | 35 | 兼容性与迁移测试 |

判定规则：

- 运行时 = 排除 `app01/`、`r22_account/`、`scripts/`、`tests/`、`migrations/` 的项目代码；
- 模式：`from app01.models`、`app01.models.`、`get_model('app01')`、
  SQL 表名 `app01_<业务表>`；
- 安全状态表 `app01_account_security_state` / `app01_login_device` 不在旧业务表范围，
  单独列出（产品中间件需要）。

---

## 2. 唯一的运行时回退已移除

| 项 | 变更 |
|---|---|
| 文件 | `smass_workspace/services/student.py` |
| 函数 | `dormitory_of(record)` |
| 变更前 | 先读 `StudentRecord.extra.dormitory`；缺失时 `from app01.models import Student` 并按学号回退 |
| 变更后 | **只读 `extra.dormitory`**，不再 import 或查询旧表 |
| 兼容性 | 旧住宿表已由迁移写入 `extra`；产品库 app01 表本就为空，页面行为不变 |
| 验证 | 依赖扫描 runtime=0；产品层 40 例 OK；断库 13 页全 200 |

---

## 3. r22 兼容层的状态

| 项 | 状态 |
|---|---|
| 是否注册 | 是（`settings_product.INSTALLED_APPS`） |
| 是否被产品代码 import | **否**（identity/legacy_compat 零引用） |
| 审计依赖 | `smass_organization/services.py` 与 `export.py` 调用 `r22_account.audit`，只写 `AccountAuditEvent`，**不读 app01 表** |
| 旧表名常量 | 保留在 `identity.py` / `legacy_compat.py`，供迁移与兼容测试 |
| 退役建议 | 兼容测试稳定后，可将 r22 从产品 INSTALLED_APPS 移除（需独立迁移窗口，避免 127 表结构变化） |

---

## 4. app01 中仍需保留的组件

| 组件 | 为什么保留 |
|---|---|
| `AccountSecurityState` | 密码生命周期/会话世代（`PasswordLifecycleMiddleware`） |
| `LoginDevice` | 会话/设备管理 |
| `app01.middleware.*` | 隐私响应、密码生命周期、会话安全 |
| `app01.services.accounts` | 历史密码兼容/账号服务（部分被中间件引用） |
| app01 旧业务表 | 仅迁移工具与兼容测试使用；产品运行不读写 |

> 保留 app 注册 ≠ 依赖旧库。旧业务表在产品库中为 0 行，
> 断库测试证明表不可用时产品仍运行。

---

## 5. 默认启动配置统一

| 项 | 变更 |
|---|---|
| `manage.py` | 默认 `DJANGO_SETTINGS_MODULE=smass.settings_product` |
| 实测默认 | `settings_product` / `smass_product_dev` / `smass.urls_product` |
| 旧配置 | 必须显式 `--settings=smass.settings`（app01 188 例、tests_e2e 16 例已验证） |
| 效果 | `python manage.py runserver` 不再进入旧 app01 系统 |
| 回归适配 | `r10_full_regression.py` 中 app01/tests_e2e 显式传 `smass.settings` |

---

## 6. 旧 URL / 模板 / 设置

| 项 | 现状 |
|---|---|
| `smass/urls.py` | 旧总入口，默认不再使用（`urls_product` 为产品入口） |
| `urls_admin/student/teacher` | 不在 `urls_product` |
| `templates/admin|student|teacher|layout|login` | 未被产品 URL 引用 |
| `settings_r4`–`settings_r22`、`settings_s*` | 仅独立测试/兼容，产品不使用 |
| `settings.py` | 保留供旧测试；默认启动已改为产品 |

---

## 7. 断库运行测试

`scripts/db_unify_detached_test.py` 在验证库执行：

1. 重命名 16 张 app01 旧业务表为 `_retired_*`；
2. 登录 uni_student / uni_teacher / uni_admin；
3. 访问 13 个关键页面；
4. `finally` 恢复表名。

结果：**全部 200/302，失败 0**。
证明：旧业务表不可用时，三端登录、学籍、寝室、考勤、课表、审批、管理端均正常。

---

## 8. 仍保留旧引用的场景（不阻断）

| 场景 | 位置 | 是否影响产品 |
|---|---|---|
| 迁移脚本 | `scripts/legacy_migration.py` | 否（一次性） |
| 兼容测试 | `app01/tests`、`r22_account/tests` | 否（独立配置） |
| 旧后台视图 | `app01/views/**` | 否（未挂载产品 URL） |
| r22 表名常量 | `r22_account/identity.py` | 否（零调用） |
| 安全状态表 | `app01/models.py` | 是（产品必需，非旧业务） |

---

## 9. 未删除代码的理由

- 1800 例回归中 app01 188 例、r22 117 例仍依赖旧代码；
- 删除会造成历史迁移与兼容测试不可复现；
- 本轮目标是"运行时零依赖"，不是"删除旧代码"；
- 代码删除应在正式切换成功、保留期结束后作为独立清理任务。
