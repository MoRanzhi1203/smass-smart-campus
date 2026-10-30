# SMASS 技术决策记录（公开版）

本文件汇总**有长期维护价值**的技术决策与实测结论。Agent 运行账本、会话记录、
过程截图等研发流水保存在本地 `.local/`（不进入版本库，见
[Repository Governance](#11-仓库治理与本地资料) ）。

> 本文件不含凭据、密码哈希或个人数据。涉及安全治理时只描述做法与结论。

---

## 1. 认证与身份模型

| 决策 | 内容 | 依据 |
|---|---|---|
| `AUTH_USER_MODEL` | 保持 Django 默认 `auth.User`，**从未指向自定义用户模型** | 全仓 `settings*.py` 均未设置该键；`app01` 中不存在 `UserInfo` 类 |
| 旧系统身份 | `app01` 用 `session['info']`（`id`/`type`/`name`） | 历史实现，保持不动 |
| 新系统身份 | `r21_account.Account` + `AccountRole`（Django Group 承载权限） | R2.1 |
| 双身份并存 | `r22_account.identity` 五类解析：`legacy` / `account` / `dual` / `conflict` / `anonymous` | 权威依据是 `LegacyAccountLink`，**不**用登录名或主键巧合推断 |
| 冲突处置 | 新旧身份同时存在但链接缺失/不匹配 → `conflict`，**一律拒绝**并告警 | fail-closed |
| 正式认证切换 | **未执行** | `AUTHENTICATION_SWITCH = NOT_AUTHORIZED` |

---

## 2. 数据库与容量

| 指标 | 实测值 | 说明 |
|---|---|---|
| MySQL 版本 | `8.0.18` | |
| 正式库 `smass` | 26 表 / 111 列 | 全程只读，指纹 `b914b39c…` 前后一致 |
| `max_connections` | **20** | `SHOW VARIABLES` 实测 |
| `CONN_MAX_AGE` | **0**（不启用持久连接） | 每线程用完即还，避免长期占用放大 1040 风险 |
| 连接耗尽错误 | 曾观测 `OperationalError:1040`（Too many connections） | 发生在**建连阶段、事务未开始**，因此不产生半写数据 |

### 并发结论（R2.2.1 实测）

- 短事务下 5 / 10 / 15 / 20 / 25 / 30 / 40 / 50 worker 均 **0 错误**；
- 真正的风险是**长事务占用连接**，而非 worker 数量本身；
- 因此业务侧应避免在请求周期内持有长事务，而不是一味压低并发。

### 隔离库命名约束

每个版本使用独立库前缀，`settings_*` 内**强制校验**，写错直接启动失败：

| settings | 库名前缀 |
|---|---|
| `settings_r4` | `smass_r4_` |
| `settings_r5` | `smass_r5_` |
| `settings_r10` | `smass_r10_` |
| `settings_r11` | `smass_r11_` |
| `settings_r16` | `smass_r16_` |

正式 `smass` 库**只读**：不 migrate、不 flush、不删表。

---

## 3. 密码与历史哈希治理

| 决策 | 内容 |
|---|---|
| 历史 MD5 兼容 | 仅在**校验**时兼容，命中后立即升级为 PBKDF2 |
| 旧密钥 | 已确认泄漏（曾硬编码于源码与 Git 历史）。**代码中不再保留任何字面量**；改为从环境变量 `SMASS_LEGACY_MD5_SECRET_KEY` 注入 |
| 迁移开关 | `SMASS_LEGACY_MD5_COMPAT`，**默认关闭**；未开启时历史 MD5 账号一律拒绝登录并写审计 |
| 密钥与 `SECRET_KEY` | 两者已彻底解耦；`SECRET_KEY` 读 `DJANGO_SECRET_KEY`，`DEBUG=False` 且缺失时直接启动失败 |
| 密码生命周期 | `app01.AccountSecurityState` 独立表承载强制改密/停用/临时口令/会话世代；策略 `PASSWORD_LIFECYCLE` 全部默认 OFF |
| 会话失效 | 重置/改密/停用时 `session_epoch += 1`，旧会话立即失效；改密后为当前会话写新世代，不误伤自己 |
| 对真实用户重置 | **未执行**（需数据所有者 + 安全双重授权） |

> 教训：删除源码里的一个字符串**并不能**修复已泄漏的 Git 历史。可上传的历史
> 必须经过独立镜像重写并在克隆侧复验（见 §11）。

---

## 4. 授权模型

五维门面 `r21_account/authorization.py`，默认拒绝：

1. **RBAC**：动作 → Django permission；未知动作拒绝。
2. **组织域**：`scope_queryset()` 直接返回已过滤 QuerySet；`scope_college` 为空时返回空集
   （"空"不等于"全部"，这是最容易被写错的默认值）。
3. **对象级**：`require_object()` 三检（存在 + 动作 + 可见集合），判定口径与列表页一致，
   避免"列表看不到但详情能打开"。
4. **字段级**：**允许列表**（未列出即不可见，新增字段默认不可见）；敏感字段（身份证/手机/密码）
   即使可见也走掩码，仅系统管理员可拿原值。
5. **业务状态**：状态转换表，未知转换默认拒绝，可由 `AUTHORIZATION_TRANSITIONS` 扩展。

职称（教授/副教授/讲师/实验员/行政双肩挑/外聘）**只**影响排课的默认周课时上限，
**不产生任何授权效果**。

---

## 5. 排课算法选择

| 决策 | 内容 |
|---|---|
| 求解器 | **不使用 CP-SAT**：本机实测无 `ortools` / `pulp` / `mip` / `z3` / `networkx`；安装需额外依赖审计与体积成本 |
| 替代方案 | 确定性构造 + 有限回溯（`deterministic-constructive-v1`） |
| 最优性声明 | **不声称全局最优**；只声称"硬冲突为 0，或明确报不可行 + 可读原因" |
| 确定性 | 同输入必得同结果（候选排序含 `room.code` 作为决胜键） |
| 硬约束兜底 | `ScheduleEntry` 上四个唯一约束（教室/教师/群体/需求）把硬约束下沉到数据库 |
| 独立复核 | `verify_run()` 与求解器分开实现，发布前必须通过 |
| 维护期处理 | 排课结果是周模板；维护期覆盖学期内任一实例即阻塞该 `(weekday, period)`（保守但安全） |

---

## 6. 数据导入导出（S25）

| 决策 | 内容 |
|---|---|
| 引擎位置 | `smass_data_exchange`，**纯库无模型**，不新增迁移 |
| 模板 | 由单一版本化 `DatasetSchema` 生成 `.xlsx`（Data/Instructions/Options）与 UTF-8 BOM `.csv` |
| 示例行识别 | 用显式 `__example__` 标记列，**不按值猜**（按值猜会静默丢弃与示例同值的真实数据） |
| 预检 | **零业务写入**；返回摘要 + 签名令牌 |
| 令牌绑定 | 文件 SHA256 + schema 版本 + 引擎版本 + 操作者 + 30 分钟有效期 |
| 提交 | 重新解析、重新校验，不信任预检结果；有错误默认整体拒绝 |
| 幂等 | 重复提交同一文件第二次全部 `skip`；数据库唯一约束是最后防线 |
| 文件安全 | 类型白名单、魔数校验、压缩炸弹上限（64 MB / 120:1）、8 MB 与 5000 行上限、`data_only=True` 不执行公式 |
| 编码 | 依次尝试 `utf-8-sig` / `utf-8` / `gb18030`，全失败即报错，**不做 replace 静默降级** |
| 导出安全 | 字段级裁剪 + 公式注入中和（`= + - @ \t \r \n` 开头加单引号）+ 敏感字段掩码 |

---

## 7. 场地与预约（R16）

| 决策 | 内容 |
|---|---|
| 时间不重叠 | MySQL CHECK 无法表达区间互斥，因此在事务内 `Room.objects.select_for_update()` 锁房间行后再查冲突，同房间请求串行化 |
| 占用状态 | `pending` / `approved` / `checked_in` 均视为占用，避免两个待审批请求同时被批准 |
| 审批 | 需要审批的房间先进 `pending`；**禁止自批**（`SELF_APPROVAL_DENIED`） |
| 资格 | `requires_qualification` 的房间需未过期 `RoomQualification`；过期即拒绝 |
| 释放 | 取消/释放写 `released_at`，该时段**立即可被再次预约** |
| 授权域 | 系统管理员全量；学院管理员按 `building.campus` 匹配 `scope_college`（当前唯一可用组织维度，待"楼宇归属学院"落地后调整）；教师/学生仅本人 |

---

## 8. 前端与测试约定

| 项 | 约定 |
|---|---|
| 页面基座 | 隔离模块统一 `{% extends "r10/base.html" %}` |
| 登录跳转 | 每个 `urls_*` 必须配套设置 `settings.LOGIN_URL`，否则会串到别的模块登录页 |
| 测试命令 | `python manage.py test <app> --settings=smass.settings_<x>` |
| 服务器端设置 | 子进程输出为 UTF-8；`subprocess.run(..., text=True)` 必须显式 `encoding='utf-8'`，否则 Windows 按 GBK 解码会抛 `UnicodeDecodeError` 并把通过的套件误报为失败 |
| 测试库残留 | 强行终止测试进程会留下 `test_*` 库；下次 `CREATE DATABASE` 失败。出现 0 用例快速失败时先清理残留测试库 |
| 浏览器 E2E | Playwright；WebKit 在 Windows 的 `load` 事件偶发滞后，诊断性测试的导航超时放宽到 30s（可由 `R10_H3_TIMEOUT_MS` 覆盖） |

---

## 9. 模型与常量引用

- `SEMESTER_CHOICES` / `STATUS_OPEN` / `STATUS_CHOICES` 是**模型类属性**（定义在类体内），
  不是模块级常量。引用方式为 `AcademicTerm.SEMESTER_CHOICES`、
  `TeachingSection.STATUS_OPEN` 等。
- `app01` 的 `Admin` / `Student` / `Teacher` 三张表**结构未改**；新增状态放在独立表
  `app01_account_security_state`，避免对正式库做破坏性 ALTER。

---

## 10. 版本功能状态（截至最近一次实测）

| 模块 | 状态 |
|---|---|
| G0 GitHub 私有归档 | `VERIFIED`（快照/扫描/脱敏/远端克隆复验） |
| S0 基线与门禁 | `TESTED`（基线 930 例复现，严格门禁脚本） |
| S01 / S02 / S03 / S06 | `TESTED`（密钥治理、密码生命周期、身份权威、五维授权） |
| S25 / S25-R4 / S25-R5 | `TESTED`（引擎 + 两套适配器，85 例） |
| R16-RESOURCE | `TESTED`（42 例，模型与服务层） |
| R11 / R11-UI | `TESTED`（22 + 18 例） |
| 其余 S04–S24、S25-PERF、R12–R20、R16-UI | `PENDING`（未开发，未虚报） |

研发账本共 44 项、12 项 `TESTED`。完整状态见本地 `.local/agent-sessions/dsh_run/`
（不进入版本库）。

---

## 11. 仓库治理与本地资料

| 决策 | 内容 |
|---|---|
| 保留资料位置 | 全部**项目内**。不再使用项目外归档目录 |
| 本地研发资料 | 统一放 `.local/`，整个目录被 `.gitignore` 忽略 |
| 进入 `.local/` 的内容 | 提示词（active/archive）、Agent 会话与账本、检查点、开发日志、证据、截图、数据库备份、Git 受保护备份、迁移证据、临时文件、清单 |
| 进入版本库的内容 | 源代码、迁移、测试、模板与静态资源、维护脚本、`.github/`、`docs/` 下**有维护价值**的技术文档 |
| 历史净化 | 只在**独立镜像**中重写历史；唯一工作区不被直接重写。旧 SHA→新 SHA 映射与原始 bundle 保存在 `.local/git-backups/protected/` |
| 准入检查 | `scripts/repo_admission_check.py` 检查索引、暂存区与 HEAD 树；`--selftest` 验证规则有效性。`git add -f` 无法绕过 |
| 不可声明的内容 | 不声称 GitHub 缓存、其他克隆或已泄漏凭据被物理清除；只声明受控 refs 已净化并复验 |
