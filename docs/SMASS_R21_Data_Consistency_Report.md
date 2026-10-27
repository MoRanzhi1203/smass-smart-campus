# SMASS R2.1 数据一致性报告（Data Consistency Report）

## 1. 唯一写入权威（分阶段）

| 阶段 | 权威 | 说明 |
|---|---|---|
| P2 回填 | 旧表 | 只读旧表 → 写新表；`LegacyAccountLink` 保证一对一映射 |
| P3 双写 | **服务层**（`r21_account/dual_write.py`） | 单事务同时写两表；任一侧失败整体回滚 |
| P4 读切换 | 计划为新表 | **未实施**（NOT DONE） |

不使用 signal 作为同步手段（无事务保障、难测试、与批量操作冲突）。

## 2. 哈希一致性

- 回填：`account.password = row.password`（原样赋值）
- 双写：`make_password()` **一次**，两表赋同一字符串
- 校验：`verify_account_consistency` 逐条比对 `Account.password == 旧表 password`

实测：`legacy rows=6 / accounts=6 / links=6` → **PASS**（0 不一致）。

## 3. 故障注入结果（`test_dual_write.FaultInjectionTests`）

| 注入点 | 期望 | 实测 |
|---|---|---|
| `Account.save` 抛错 | 旧表回滚 | PASS（旧表无该行） |
| `StudentProfile.create` 抛错 | 两表均回滚 | PASS |
| 重复学号 | 抛 `DualWriteError`，不写入 | PASS |
| 未知登录名改密 | 抛 `DualWriteError` | PASS |

## 4. 双写动作覆盖

| 动作 | 函数 | 测试 |
|---|---|---|
| 新建学生 | `create_student` | 哈希一致 + 档案 + 映射 + 角色 |
| 新建教师 | `create_teacher` | 同上 |
| 修改密码 | `change_password` | 两表哈希一致、`must_change_password=False` |
| 停用 | `deactivate` | `is_active=False` + 原因 |
| 启用 | `activate` | 恢复 `is_active`、清 `deactivated_at` |
| 角色变更 | `services.grant_role` / `revoke_role` | 事务内同步 Group；撤销即时失效 |

## 5. 回滚演练

| 场景 | 方式 | 结果 |
|---|---|---|
| 回填回滚 | `backfill_accounts_r21 --rollback` | 删除映射与账号（级联 Profile/Role） |
| 双写失败 | 事务自动回滚 | 已验证 |
| 原型整体回退 | `migrate r21_account zero`（**仅原型库**） | 未执行（会删原型数据），保留为受控操作 |

## 6. 未做 / 限制

| 项 | 说明 |
|---|---|
| 正式库回填 | NOT DONE |
| 双写一致性**定时任务** | 未做（当前为手动命令） |
| 双写期间的**读**一致性 | 读路径仍走旧表；新表读取未启用 |
| 并发双写冲突 | 仅用唯一约束 + 事务隔离，未做高并发压测（无基准数据，不臆造结论） |
| 旧表与新表字段全集对齐 | 当前 Profile 只映射核心字段（班级/学院用名称字符串） |
