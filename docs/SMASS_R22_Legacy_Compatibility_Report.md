# SMASS R2.2 旧业务兼容报告（Legacy Compatibility）

- 测试：`r22_account/tests/test_h3_legacy_compat.py`（**7/7 PASS**）
- 适配层：`r22_account/legacy_compat.py`
- **`app01` 零改动**

## 1. 适配原理

`app01` 视图与装饰器只认 `session['info']`；R2.2 的认证主体是 `request.user`(Account)。
适配层在**旧路由前缀**（`/admin/`、`/student/`、`/teacher/`）上，按 `LegacyAccountLink`
把 Account 映射成等价 `session['info']`。

安全边界：

| 规则 | 实现 |
|---|---|
| 映射权威 | 只用 `LegacyAccountLink(source_table, source_pk)` |
| 不覆盖既有身份 | `if request.session.get('info'): return False` |
| conflict/匿名不桥接 | `identity.kind not in ('account','dual')` → 直接返回 |
| 仅 staging | `R22_FLAGS.legacy_bridge`（正式 settings 无此键） |

## 2. 覆盖矩阵

| # | 场景 | 结果 |
|---|---|---|
| 1 | Account(admin, 有映射) → `/admin/student/list/` | **200**，页面含真实数据 |
| 2 | Account 无 `LegacyAccountLink` → 同页 | 302/403（拒绝） |
| 3 | 旧 `session['info']` 直接访问 | **200**（原路径仍可用） |
| 4 | conflict（account + 不匹配 legacy） | **403** |
| 5 | student 身份访问 admin 页 | **403** |
| 6 | 匿名访问 | 302/403 |
| 7 | 客户端伪造 `?id=999&type=admin` | 无效，session 身份仍是 `001` |

## 3. 本轮发现的真实缺陷

**身份解析缓存未随桥接失效**：

```
桥接前 kind=account → 写入 session['info']
RoutePolicy 读到缓存的 kind=account → /admin/ 不在 account 允许列表 → 302
```

修复：桥接成功后清空 `request._r22_identity_cache['identity']`，
使后续解析得到 `dual`（account + 匹配 legacy）→ 放行。

这是"缓存与身份变更顺序"的典型缺陷，已由 H3 测试锁定。

## 4. 旧 URL 覆盖现状

| 路由 | 状态 |
|---|---|
| `/admin/*`（含 `/admin/student/list/`） | **PASS**（真实页面渲染） |
| `/student/*`、`/teacher/*` | 策略与桥接已就绪；**本轮未逐个页面验证**（PARTIAL） |
| `/login/`（旧登录页） | 隔离配置未挂载（有意避免双登录入口） |

## 5. 未做

| 项 | 状态 |
|---|---|
| 逐个遍历 app01 全部页面 | NOT RUN（仅代表页面） |
| 旧页面的写操作（新增/删除/导入） | NOT RUN |
| 旧页面的浏览器级验证 | NOT RUN（H5 只覆盖认证流程） |
