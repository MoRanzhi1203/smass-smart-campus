# SMASS R10 Security Regression（H6）

- 设置：`smass.settings_r10`（跨 settings 验证另见 §6）
- 测试：`smass_operations/tests/test_r10_h6_security.py`（27 例）
- 结果：**27/27 PASS**；operations 回归 **289/289 PASS**

## 1. 身份矩阵

5 类身份 × 代表端点，全部符合预期：

| 身份 | 管理表单（4） | staff 页面（4） | 业务列表 |
|---|---|---|---|
| 匿名 | 302/403 | 302/403 | 302/403 |
| 无角色账号 | **403** | 403 | 403 |
| 停用账号 | 无法登录 | — | — |
| student | 403 | 403 | 仅本人档案 |
| teacher | 403 | **200** | 任课范围 |
| college_admin | 部分（学年新建 403） | 200 | 本院 |
| system_admin | 200 | 200 | 全部 |

关键：**无角色账号不会降级为"全可见"**（`scoped_students == 0`）。

## 2. 跨面一致性（本轮重点）

同一账号通过不同表面看到的集合必须相同：

| 表面 | 通道 |
|---|---|
| 服务层基准 | `scoped_students(account).count()` |
| CSV 导出 | `/r4/students/export/` |
| R7 指标 | `compute_metric('students_scoped', account)` |

实测：

| 账号 | 服务层 | CSV | R7 指标 |
|---|---|---|---|
| system_admin | 9 | 9 | 9 |
| college_admin(A) | 6 | 6 | 6 |
| student | 1 | **403**（不允许导出） | — |
| 无角色 | 0 | 403 | — |

**student 的 403 是正确行为**（导出仅对 admin/college/teacher 开放），
已单独断言，不是缺陷。

## 3. 小样本抑制不泄漏

B 院管理员（B 院 3 人 < 阈值 5）：

- 服务层 `scoped_students` = 3（管理员自己可以数）
- **R7 指标 = 0 且 `suppressed=True`**
- UI 只显示"已抑制"徽章

验证了"服务层知道，但对外输出被抑制"。

## 4. 伪造请求不提权

| 攻击 | 结果 |
|---|---|
| student POST 建组织 | **403**，未创建 |
| POST body 塞 `role=system_admin` | **403** |
| teacher 改学生档案 | **403**，数据未变 |
| 他院管理员改本院学生 | **404**（不泄露存在性），数据未变 |
| API 无 token | **401** |
| API 已撤销服务账号 | **401** |

## 5. 密码中间件与 legacy bridge 共存

| 检查 | 结果 |
|---|---|
| `must_change_password` 账号访问业务页 | 302 → `/r21/change-password/` |
| 同账号 AJAX | **403** + `code=must_change_password` |
| 改密后 `session` 里出现 `info` 键（降级） | **未出现** |
| 改密后可访问业务页 | 200 |

**没有发生 session 降级**——新身份生效后不会回退到 `session['info']`。

## 6. 跨 settings 回归（发现 2 个真实缺陷）

H6 在 `settings_r10` 下运行时暴露了两处**只在 r10 路由下才出现**的回归：

### 缺陷 1：`/r4/students/export/` 被 `<student_no>` 抢占

- 现象：`GET /r4/students/export/` → **404**
- 根因：U3 加学生详情页时把 `r4/students/<str:student_no>/` 注册在
  `r4_patterns` 之前，`export/` 被当成 `student_no='export'`
- 为什么之前没发现：`test_r4_export` 跑在 `settings_r4`（`urls_r4` 无该路由）
- 修复：在 `urls_r10` 把 `r4/students/export/` 显式排在 `<student_no>` 之前

### 缺陷 2：R7 看板在 r10 下丢了 JSON 分支

- 现象：`GET /r7/dashboard/` 带 `X-Requested-With` 返回 **HTML** 而非 JSON
- 根因：U6 的新视图 `ui_views.dashboard_page` 只写了 `render` 分支，
  丢失了旧视图的 JSON 分支
- 为什么之前没发现：`test_r7_browser` 跑在 `settings_r7`（`urls_r7` → 旧视图）
- 修复：给 `dashboard_page` 补 JSON 分支，并保留 `metric`/`code` 双键

**这两条正是"跨 settings 回归"的价值**：同一份代码在不同 URLconf 下行为不同，
只跑单套 settings 永远发现不了。

## 7. 审计一致性

| 检查 | 结果 |
|---|---|
| 授予角色写入 `AccountRole` | PASS |
| 重复授予不产生第二行 | PASS（DB 唯一索引兜底） |
| 撤销+重授予保留历史（2 行，1 active） | PASS |

## 8. 与计划的对应

| 计划要求 | 本测试 |
|---|---|
| 多角色/停用/匿名/陈旧会话/冲突身份 | §1 |
| 伪造请求参数不得提权 | §4 |
| R4 scope 跨 UI/API/CSV/R7 一致 | §2 |
| 密码中间件与 legacy bridge 共存 | §5 |
| 审计保留失败/回退事件 | §7 |
| 并发授予与任务分配遵守 H2 | H2 测试（`test_r10_h2_uniqueness`，4 线程） |
| 跨 settings 回归 | §6（发现 2 个缺陷） |

## 9. 未覆盖

| 项 | 状态 | 原因 |
|---|---|---|
| 陈旧 legacy session（R2.1 时代的 session 复用） | **NOT RUN** | 需要构造旧格式 session 数据；当前隔离库无历史 session |
| 真实 API 级并发（多进程） | **PARTIAL** | H2 已用 4 线程验证 DB 约束；API 层并发未单独跑多进程 |
| 审计 payload 的敏感字段扫描 | **PARTIAL** | 代码审查确认只记 action/actor/status，未做自动化 payload 断言 |
