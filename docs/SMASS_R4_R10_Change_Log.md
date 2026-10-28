# SMASS R4–R10 变更清单

- 分支：`feat/smass-r4-r10-integrated-platform`
- 基线：`7df6e19`

## 1. 新增代码

| 文件 | 作用 |
|---|---|
| `smass_organization/__init__.py` / `apps.py` | R4 app |
| `smass_organization/models.py` | 7 个模型（组织树/成员/档案/变更/字段字典/导入批次/错误行） |
| `smass_organization/services.py` | 类型约束、防环、移动审计、字段级权限、导入预检/提交 |
| `smass_organization/views.py` | 8 个端点（组织/学生/导入/health） |
| `smass_organization/migrations/0001_initial.py` | 建表迁移 |
| `smass_organization/tests/test_r4.py` | 23 例测试 |
| `smass/settings_r4.py` | 隔离配置（库 `smass_r4_org`） |
| `smass/urls_r4.py` | 隔离路由 |
| `templates/r4/unit_list.html`、`student_list.html` | 真实渲染模板 |

## 2. 未修改（保持隔离）

| 项 | 说明 |
|---|---|
| `app01/*` | 零改动 |
| `smass/settings.py` | 未改 |
| `AUTH_USER_MODEL` | 未改 |
| 既有迁移 | 未重写 |
| 正式认证入口 | 未切换 |

## 3. 新增数据库

| 库 | 内容 | 状态 |
|---|---|---|
| `smass_r4_org` | R4 隔离库（合成数据） | 保留 |

## 4. 测试变化

| 套件 | 之前 | 现在 |
|---|---|---|
| r22_account | 94 | 94 |
| r21_account | 72 | 72 |
| app01 | 114 | 114 |
| tests_e2e | 16 | 16 |
| **smass_organization（新）** | — | **23** |
| 合计 | 296 | **319** |

## 5. 本轮修复的缺陷

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | 类型校验先于成环校验，把"环"误报为 `INVALID_HIERARCHY` | 判定顺序改为**环优先** |

## 6. 结论

R4 = `CORE_COMPLETE / PARTIAL`。
R5–R10 = `NOT_STARTED`（未创建空壳）。
