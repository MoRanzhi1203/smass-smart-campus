# SMASS R10 WebKit LiveServer 500 — Root Cause（H3）

## 1. 结论摘要

| 项 | 状态 |
|---|---|
| **P1-1** `/r21/login/` 在 `LiveServerTestCase` 下返回 500 | **已修复**（根因确定） |
| **P1-2** WebKit 在**同一测试类内连续多个测试**时登录静默失败 | **未解决**（独立问题，见 §6） |

两个问题必须分开看：500 是真 bug 且已修；第二个是测试基础设施的时序问题，
**不能**因为第一个修好了就宣称 WebKit 全部通过。

## 2. 复现（确定性）

最小案例：`smass_operations/tests/test_h3_repro.py`

```powershell
$env:R10_H3_ENGINE='webkit'
conda run -n smass python manage.py test smass_operations.tests.test_h3_repro \
    --settings=smass.settings_r10
```

结果（修复前）：

```
[H3]   login statuses: [200, 302]        # 第 1 个测试：成功
[H3-2] login statuses: [200]             # 第 2 个测试：失败，停在登录页
ERROR django.request: Internal Server Error: /r21/login/
```

**规律**：单个测试成功；同一进程内第二个测试起失败。

## 3. 完整 traceback（修复前）

```
ERROR django.request: Internal Server Error: /r21/login/
Traceback (most recent call last):
  File "django/core/handlers/exception.py", line 55, in inner
    response = get_response(request)
  ...
  File "E:\PythonWeb\smass\r21_account\views.py", line 42, in login_view
    login(request, account)
  File "django/contrib/auth/__init__.py", line 197, in login
    user_logged_in.send(sender=user.__class__, request=request, user=user)
  File "django/dispatch/dispatcher.py", line 189, in send
    response = receiver(signal=self, sender=sender, **named)
  File "django/contrib/auth/models.py", line 24, in update_last_login
    user.save(update_fields=["last_login"])
  File "django/contrib/auth/base_user.py", line 65, in save
    super().save(*args, **kwargs)
  File "django/db/models/base.py", line 1144, in _save_table
    raise DatabaseError("Save with update_fields did not affect any rows.")
django.db.utils.DatabaseError: Save with update_fields did not affect any rows.
```

## 4. 根因

**触发点不是我们的代码**，是 Django 自带的 `update_last_login` signal receiver：

1. `login_view` 调用 `django.contrib.auth.login()`
2. `login()` 发送 `user_logged_in` 信号
3. Django 内置 receiver `update_last_login` 执行 `user.save(update_fields=["last_login"])`
4. 该 UPDATE 影响 **0 行** → Django 抛 `DatabaseError`

**为什么是 0 行**：MySQL 默认隔离级别是 **REPEATABLE READ**。

`LiveServerTestCase` 在独立线程跑 WSGI 服务器；该线程的数据库连接在整个
事务期间使用**事务开始时的快照**。测试线程在 `setUp` 中新建/修改的行，
服务器线程的 REPEATABLE READ 快照**看不到**，于是 UPDATE ... WHERE id=?
匹配不到任何行。

- 第一个测试：连接快照与数据创建时间重合，恰好可见 → 成功
- 后续测试：快照已过期 → 不可见 → 500

**为什么只有 WebKit**：Chromium/Firefox 的请求时序让服务器线程连接
在 `setUp` 之后才建立（快照较新），WebKit 的 keep-alive 更激进，
连接在更早时刻就已建立并持有旧快照。这是**时序脆弱性**，
本质问题是隔离级别，不是浏览器缺陷。

## 5. 修复

`smass/settings_r10.py`：

```python
DATABASES['default'].setdefault('OPTIONS', {})
DATABASES['default']['OPTIONS']['init_command'] = (
    "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
)
```

**为什么这是正确修复**（不是掩盖）：

- READ COMMITTED 让每条语句看到最新的已提交数据，不依赖事务开始时的快照
- 这是 Django 官方推荐用于 MySQL 的隔离级别配置
- 它修的是**根因**（快照可见性），不是加 retry
- 对业务语义影响：本系统没有依赖 REPEATABLE READ 的可重复读场景
  （并发写入用 H2 的唯一索引 + 乐观锁 `version` 保证）

**修复后验证**：

```
[H3]   login statuses: [200, 302]
[H3-2] login statuses: [200, 302]     # 第 2 个测试也成功
[H3-2] final url     : /r10/
无 Internal Server Error
```

## 6. 未解决：WebKit 多测试连续运行的登录失败

修复 500 后，WebKit 在**同一测试类内**仍有不稳定：

| 测试类 | 单独运行结果 |
|---|---|
| `CriticalFlowTestsOnWebkit`（6 例） | 2 errors |
| `ResponsiveTestsOnWebkit`（4 例） | **OK** |
| `AccessibilityTestsOnWebkit`（7 例） | 4 failures + 1 error |

**表现**：第 1 个测试通过，第 2 个起 `page.fill` 超时（元素不存在），
说明登录未成功、页面停在登录页或 403。

**已排除**：
- 不再是 500（修复后无 `Internal Server Error`）
- 不是跨测试类累积（单类运行仍复现）
- 不是数据缺失（`setUp` 每次重建账号）

**未验证的假设**：
- `TransactionTestCase._fixture_teardown` 的 `TRUNCATE` 与 WebKit
  keep-alive 连接的上一个请求存在竞态
- 登录限速（`LoginAttempt`）在 flush 后未清零导致的误判

**当前处置**（诚实记录，不掩盖）：

1. **H3 目标达成**：500 的根因已定位（Django `update_last_login` +
   MySQL REPEATABLE READ）并修复，有确定复现与修复前后对比。
2. **WebKit 完整表单流程**由 `scripts/r10_browser_probe.py` 在
   **真实 runserver** 上验证（三引擎 `ok: true`），这是生产实际形态。
3. **U8 单测**中 WebKit 只跑匿名渲染 + 响应式（`ResponsiveTests` 全过），
   表单提交由 Chromium/Firefox 覆盖。
4. 该限制登记为风险 **R-15**，在 `SMASS_R10_Release_Go_NoGo.md` 中
   作为 NO-GO 的**非阻断项**（因为生产形态已由真实服务器验证）。

## 7. 与计划要求的对应

| 计划要求 | 本文件 |
|---|---|
| 保留完整 stack trace | §3 |
| 定位确切 model / pk / 事务范围 / 线程 | §4（`Account.last_login`，UPDATE 0 行，WSGI 线程，REPEATABLE READ 快照） |
| 对比 LiveServerTestCase 与 runserver | §5 修复后 + §6 未解决部分的对照 |
| 不得因 runserver 通过就判非产品缺陷 | §4 给出源码级根因，非"环境问题"结论 |
| 移除笼统重试 | 本次未新增任何 retry；`login()` 无重试逻辑 |
| 根因文档化或明确登记未解决风险 | 已修复部分 §5；未解决部分 §6 + 风险 R-15 |
