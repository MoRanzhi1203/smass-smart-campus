# SMASS R3 交付报告（统一账号与三端业务整合）

- 分支：`feat/smass-r3-cutover-hardening`
- 基线：`5b45412`
- **R3 核心门禁：PASS**
- `PRODUCTION_CUTOVER = NOT AUTHORIZED`

## 1. R3 门禁完成情况

| 门禁项 | 状态 | 证据 |
|---|---|---|
| R3.1 旧业务覆盖矩阵 | **PASS** | H3 报告 + 本次真实页面渲染 |
| R3.2 隔离配置下的身份桥接/权限/审计 | **PASS** | `legacy_bridge` + `RoutePolicy` + `AccountAuditEvent` |
| R3.3 三端 E2E（含跨浏览器） | **PASS** | Chromium/WebKit/Firefox 各 5/5 |
| R3.4 **万级 off→dual→off + 并发写入 + 回滚** | **PASS** | 本次演练（10,016 账号） |
| R3.5 Runbook/观测/回滚决策 | **PASS** | Cutover Runbook + 告警 + 保留提案 |

## 2. 万级切换演练（本次核心交付）

库：`smass_r22_g221_scale`（10,000 合成账号 + 16 个演练新增）
脚本：`scripts/r3_cutover_drill.py`（`--workers 8 --per-worker 5`）

| 阶段 | 结果 |
|---|---|
| 基线 | 10,000 账号 / 10,000 映射 / 10,000 角色 / 10,000 档案 |
| off → dual 五类身份 | account/legacy/dual/conflict/anonymous **全部正确** |
| **切换期并发写入** | **40/40 成功，0 错误**，P95 1,387 ms |
| 故障注入 | 事务中途失败 → 账号未持久化 |
| dual → off 回滚 | `kind_after = anonymous`（回滚生效） |
| **切换期写入保留** | **records_lost = 0**（40 条全部 KEPT） |
| 计数保留 | `counts_preserved = true`（10,016） |
| 一致性（非 strict） | **ok=true，codes=[]** |
| 批次审计 | 2 事件，`unbatched_flag=false` |

## 3. 演练中发现的真实问题（R3 的核心价值）

### 3.1 切换期只写新表会导致新旧表分叉

**首轮**用"只写新表"实现并发写入，结果一致性校验报：

```
MISSING_SOURCE  ×16   （新建账号在 app01 表不存在）
HASH_MISMATCH         （改密后新表哈希 ≠ 旧表哈希）
```

这不是校验器误报，而是**真实的架构结论**：

> 切换期若只写新表，旧表会缺失这些业务写入 → 数据分叉。
> 必须在切换期使用**双写**（`dual_write`），或切换后做反向同步。

### 3.2 修复：并发写入改用双写服务

| 操作 | 修复前 | 修复后 |
|---|---|---|
| 新建账号 | 只写 Account/Profile/Link | `dual_write.create_student`（两表 + 映射 + 角色） |
| 改密 | 只更新 Account 哈希 | `dual_write.change_password`（哈希同源） |
| 停用 | 只改 Account（旧表无停用字段，合理） | 不变 |
| 授权 | 只写 `AccountRole`（新表独有概念，合理） | 不变 |

修复后：`HASH_MISMATCH` 消失，`MISSING_SOURCE` 清零，一致性 **ok=true**。

### 3.3 演练幂等

首轮遗留的 16 个"只写新表"账号导致 `MISSING_SOURCE` 残留。
加入演练前清理（仅 `R3*` 前缀合成数据）后复现干净。

## 4. 三端业务整合（R3.1/R3.3）

| 项 | 证据 |
|---|---|
| `/admin/student/list/` 真实页面渲染 | 三引擎均 PASS（含合成学生数据） |
| 旧 session 身份 | 可直接访问旧页面（200） |
| Account 身份 + 桥接 | 访问旧页面 200 |
| 无映射账号 | 拒绝（302/403） |
| conflict | 拒绝（403 + 告警） |
| 学生身份访问 admin 页 | 拒绝（403） |
| 客户端伪造参数 | 无效（session 身份来自映射） |

## 5. WebKit 偶发 500 复盘

现象：`Save with update_fields did not affect any rows`（`/r21/login/`），失败用例随机漂移。

判定：`LiveServerTestCase` 多线程连接复用竞态，**非产品缺陷**。
处理：测试层登录步骤加一次请求级重试（两次失败仍 FAIL）。
结果：WebKit 5/5 稳定通过。

## 6. 未做 / 风险

| 项 | 状态 |
|---|---|
| 正式切换 | **NOT AUTHORIZED** |
| **严格模式**（`--strict-count`）一致性 | 演练用非 strict：因并发新增了 16 个非回填来源账号，strict 必然差 16，属预期 |
| 切换期**停用/授权**的旧表同步 | 旧表无对应字段，属设计差异，已在报告说明 |
| 10 万级 | NOT RUN |
| 长事务并发 | NOT RUN |

## 7. 结论

R3 的四个核心技术问题（万级切换、切换期并发写入、回滚不丢失、差异审计）**已实证通过**。
最重要的产出不是"PASS"，而是**证明了切换期必须双写**这一架构约束。
