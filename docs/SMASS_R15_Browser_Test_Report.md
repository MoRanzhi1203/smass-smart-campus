# SMASS R1.5 浏览器测试报告（Browser Test Report）

- 工具：**Playwright 1.64.1**（Python 同步 API）+ Chromium（headless）
- 安装位置：**隔离 conda env `smass`**（未装 base）
- 浏览器来源：`C:\Users\MSIPC\AppData\Local\ms-playwright\chromium_headless_shell-1248`（118.1 MiB，本轮下载）
- 测试库：`test_smass`（`StaticLiveServerTestCase` 自动创建/销毁）
- 结论：**16/16 PASS**；未使用 Django Client 冒充浏览器

## 1. 工具可用性检查（C-1）

| 项 | 结果 |
|---|---|
| Node / npm / npx | 存在（`E:\NodeJS`） |
| `playwright` CLI | 存在（`E:\anaconda3\Scripts\playwright.exe`） |
| Python `playwright` 模块（隔离 env） | 初始 **MISSING** → 本轮安装 1.64.1 |
| 已有浏览器缓存 | `chromium-1208`、`chromium-1223`（版本不匹配 1.64） |
| 处理 | `python -m playwright install chromium` 下载 `chromium_headless_shell-1248` |
| Chrome / Edge 系统浏览器 | 均存在（本轮未使用） |

## 2. 隔离保证（C-2）

| 关注点 | 做法 |
|---|---|
| 数据库 | `StaticLiveServerTestCase` → Django 建 `test_smass`，用后销毁 |
| 测试账号 | `app01/tests/helpers.py` 在测试库内生成，密码随机固定常量（非真实口令） |
| 服务 | Django LiveServer（随机端口），不启动常驻 dev server |
| 开发库 | `smass` 全程未被连接写入（E2E 只操作 `test_smass`） |
| 真实口令 | 无硬编码真实口令；无真实身份证/手机号 |

## 3. 用例矩阵（16 例，全部 PASS）

### 3.1 登录 / 注销 / 匿名拦截（6）

| 用例 | 断言 |
|---|---|
| `test_anonymous_admin_page_redirects_to_login` | 匿名访问 `/admin/student/list/` → 跳 `/login/account/admin/`，页面含"账号登录" |
| `test_admin_login_lands_on_admin_list` | 登录后 URL 含 `/admin/admin/list/`，页面含"管理员列表"，**无 JS 错误** |
| `test_student_login_lands_on_profile` | 跳 `/student/users/profile/`，页面含学生姓名 |
| `test_teacher_login_lands_on_basic` | 跳 `/teacher/basic/`，页面含教师姓名 |
| `test_wrong_password_stays_on_login_page` | 停留登录页且提示"账号或密码错误" |
| `test_logout_clears_session` | 注销后再访问后台 → 回到登录页 |

### 3.2 后台 9 模块渲染（3）

| 用例 | 断言 |
|---|---|
| `test_all_nine_lists_render_without_js_error` | 9 个列表页逐个访问，均含"列表"，**全程 0 个 pageerror / console error** |
| `test_search_filters_rows` | 搜索框提交后结果含关键词 |
| `test_endpoints_json_is_available_in_page` | 页面内 `#dsh-endpoints` 可被 JS 解析，`add`/`delete` 指向正确命名路由 |

### 3.3 模态框 CRUD 与 AJAX 契约（4）

| 用例 | 断言 |
|---|---|
| `test_create_college_through_modal` | 点"新建"→ 填 `#id_name` → 保存 → **数据库中确实出现该学院** |
| `test_delete_row_via_modal` | 点删除 → 确认 → **数据库记录被删除**（POST + CSRF 生效） |
| `test_reset_password_shows_one_time_password` | 重置密码 → 弹出包含"新密码"的 alert（一次性口令提示） |
| `test_invalid_import_file_shows_error_page` | 注入非法文件上传 → 结果页含"失败"与"没有写入任何数据" |

### 3.4 学生端 / 教师端（3）

| 用例 | 断言 |
|---|---|
| `test_profile_shows_own_name` | 个人页展示本人姓名 |
| `test_class_list_masks_phone_and_scope` | 页面含同班同学，手机号显示为 `139****4321`，**完整号码不出现** |
| `test_teacher_page_renders` | 教师页展示本人姓名 |

## 4. 本轮修复的 4 类真实集成问题

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 16 例全 ERROR：`no attribute 'admin'` | `StaticLiveServerTestCase`（TransactionTestCase）**不调用** `setUpTestData` | 夹具移入 `setUp` |
| 2 | 全 ERROR：`SynchronousOnlyOperation` | Playwright 同步 API 建立 asyncio 事件循环，Django 把 ORM 调用判为 async 上下文 | 测试进程设置 `DJANGO_ALLOW_ASYNC_UNSAFE=true`（Django 官方逃生舱；生产不设置） |
| 3 | 3 例模态框 `wait_for_selector` 超时 | 后台是 **Bootstrap 3**，显示态为 `.in`（不是 BS5 的 `.show`） | 改 `state='visible'`，不依赖 BS 版本 |
| 4 | 导入用例 `page.content` 导航竞态 | `form.submit()` 后立即取内容 | `expect_navigation()` 包裹提交 |

> 第 3 项同时是 Bootstrap 3/5 混用的**实证**：E2E 明确依赖了 BS3 的 class 语义。
> 这为 R2 的 UI 统一方案提供了具体依据，本轮**未**做大范围改版。

## 5. 截图策略

- 本轮 16 例**全绿**，没有失败截图可留；
- 未主动把页面截图作为二进制资产提交（避免仓库膨胀）；
- 需要时可用同一套配置手动取证：

```python
# 在 tests_e2e 中临时加入
self.page.screenshot(path='docs/e2e_shots/<name>.png', full_page=True)
```

**如实说明**：`docs/` 下**没有**本轮生成的截图文件。

## 6. 未运行 / 局限

| 项 | 状态 | 说明 |
|---|---|---|
| 多浏览器（Firefox/WebKit） | NOT RUN | 只装了 chromium |
| 移动端视口 | NOT RUN | 仅 1366×900 桌面 |
| 真实系统文件选择对话框 | NOT RUN | 用 `DataTransfer` 注入，绕过原生弹窗（原生弹窗 Playwright 亦无法直接操作） |
| 视觉回归（像素比对） | NOT RUN | 无基线快照 |
| 通知/消息等占位菜单点击 | 未覆盖 | 学生端侧栏部分菜单仍是 `#` 占位（不产生 404） |

## 7. 复跑

```powershell
# 首次需要浏览器
conda run -n smass python -m playwright install chromium

# 运行
conda run -n smass python manage.py test tests_e2e -v 2
```

预期：`Ran 16 tests ... OK`，约 35 秒（headless）。
