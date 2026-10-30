# SMASS 仓库治理与 GitHub 历史净化 — 最终报告

任务范围：**RH0–RH10**（仓库治理、本地整理、历史净化、远端更新、克隆验证）
本轮周期：2026-10-30
研发功能状态：**未推进**（12/44 TESTED，与治理前一致）

---

## 0. 验收裁决

| 裁决项 | 结果 | 依据 |
|---|---|---|
| `REPOSITORY_HYGIENE_GO` | **PASS** | 本地资料全部在项目内 `.local/`；正式工程保留；准入检查生效 |
| `HISTORY_SANITIZATION_VERIFIED` | **PASS** | 全 refs 5280 blob 扫描：禁用路径 0、真实凭据 0 |
| `REMOTE_CLONE_VERIFIED` | **PASS** | 全新克隆 5119 文件，HEAD = `55150fc`，准入 PASS |
| `REGRESSION_VERIFIED` | **PASS** | 1212 例 / 14 套件 / 0 失败（在净化克隆上） |
| `PRODUCTION_DEPLOYMENT_NOT_AUTHORIZED` | **保持不变** | 未部署、未切换认证、未连真实收费 |

---

## 1. RH0–RH10 完成矩阵

| 阶段 | 内容 | 状态 | 关键证据 |
|---|---|---|---|
| RH0 | 状态与远端盘点 | **DONE** | `git fsck` clean；5213 跟踪文件；无远端（原仓库） |
| RH1 | A/B/C/D/U 分类 | **DONE** | 5577 文件：A 5124 / B 92 / C 5 / D 353 / U 3 |
| RH2 | `.local/` 建立与迁移 | **DONE** | 97 文件 / 2.38 MB 迁入，逐文件 SHA-256 校验，源残留 0 |
| RH3 | 正式工程规范整理 | **DONE** | 新增公开技术决策文档；清理缓存；`docs/` 只保留技术文档 |
| RH4 | 忽略规则与准入检查 | **DONE** | `.gitignore` 增补；`scripts/repo_admission_check.py` + selftest |
| RH5 | 受保护原始备份 | **DONE** | 2 个 bundle + 3 个 tar.gz + 证据，79.1 MB，SHA-256 清单 |
| RH6 | 独立镜像历史净化 | **DONE** | 路径删除 + 内容脱敏，70 commits，5280 blob 扫描 |
| RH7 | 净化数据离线验证 | **DONE** | Django check / 迁移 / 关键模块测试全部通过 |
| RH8 | 远端受控更新 | **DONE** | 10 分支 + 1 标签推送；旧不合规 refs 删除；默认分支改 `main` |
| RH9 | 远端全新克隆验证 | **DONE** | 新克隆 HEAD `55150fc`，5119 文件，准入 PASS |
| RH10 | 工程完整性与最终回归 | **DONE** | 1212 例 0 失败；正式库指纹未变；账本 12/44 未改 |

---

## 2. GitHub 仓库属性与受控 refs

| 属性 | 值 |
|---|---|
| 仓库 | `MoRanzhi1203/smass-smart-campus` |
| 可见性 | **Private** |
| 默认分支 | `main` |
| 分支保护 | `NOT_AVAILABLE_ON_PLAN`（GitHub 免费私有仓库不支持，403） |
| 标签保护 | `NOT_AVAILABLE_ON_PLAN` |

### 受控 refs（10 分支 + 1 标签）

| ref | SHA（净化后） |
|---|---|
| `refs/heads/main` | `55150fce976f7674a2467246853451639065e8a1` |
| `refs/heads/feat/smass-r11-r20-full-campus` | `55150fce976f7674a2467246853451639065e8a1` |
| `refs/heads/feat/smass-r15-r20-hardening` | `0a73bbd190baf6a956913dd36e0c2e0d6bd00cd6` |
| `refs/heads/feat/smass-r21-account-rbac` | `46e22e0f7e1fbcf43abc5859214425268bf98edb` |
| `refs/heads/feat/smass-r22-account-cutover` | `c0cbaf93f57bf39d7f97e957288525dd882272db` |
| `refs/heads/feat/smass-r22-final-hardening` | `5eef6803592a2831844eac45aff722fd452f284d` |
| `refs/heads/feat/smass-r22-g6-g8-readiness` | `0beb5556e75ec582bc2bf0c2f49bdb96016f9d3b` |
| `refs/heads/feat/smass-r221-release-readiness` | `fca642a7f795c0c90febe1f1e0dbfd16467a0516` |
| `refs/heads/feat/smass-r3-cutover-hardening` | `d20889b8466773c9b6c04920dcc546e1ec1fb555` |
| `refs/heads/feat/smass-r4-r10-integrated-platform` | `7e6ff5b74010847d87093c1739ed12e8cf98f821` |
| `refs/tags/archive-r3-20261028` | `9a70cd647194ab18512dd75e31c7658ee1b38cfc` |

`main` 与 `feat/smass-r11-r20-full-campus` **完全一致**（同一 SHA），
GitHub Compare 结果 `identical`（ahead 0 / behind 0）。

> **时点说明**：上表是 **RH9 验证时点**的远端状态（`55150fc`）。
> 本报告自身作为一次正常提交（非强推）追加到这两个 ref，因此它们的
> 当前 SHA 会在 `55150fc` 之后前进一步，差异**仅为本文档**。
> 本文件不自引用自身提交的 SHA；精确当前值以 `git ls-remote` 为准。

### 已删除的不合规 refs

| ref | 旧 SHA | 删除原因 |
|---|---|---|
| `refs/heads/archive/r10-baseline-82013b6` | `a6b232810ac51f90b70a9e55bf2ab50d7c05f069` | 该树仍含 87 个禁用文件（根目录提示词等） |
| `refs/tags/archive-r10-baseline-20261030` | `6817a138543b95270f6337f8f567e274462dff93` | 指向同一不合规历史 |

> 这两个 ref 是早期"只做字节脱敏、未做路径删除"的产物；本轮净化历史已完整
> 包含其全部合规内容，因此移除。旧 SHA 已记入 `.local` 的映射文件。

---

## 3. 历史净化检查结果

| 检查项 | 结果 |
|---|---|
| 扫描对象 | 全部 10 分支 + 1 标签的可达历史，5280 个 blob |
| 禁用路径（`docs/dsh_run/`、`docs/screenshots/`、`note/`、根级 `SMASS_*.md`、`.local/`） | **0** |
| 真实凭据（私有密钥 / AWS key / GitHub token / 非公开 `django-insecure-*`） | **0** |
| 提交消息中的敏感串 | **0** |
| Git 对象结构 | `git fsck` clean，无损坏 |
| 允许的公开 dev 默认值 | 11 处（`settings.py` 的文档化回退值），**保留** |
| 扫描器误报 | 3 处：测试代码里的**正则字面量** `django-insecure-[A-Za-z0-9…]{20,}`，已按"以 `django-insecure-[` 开头且以 `}` 结尾"判据识别为非凭据 |

### 净化动作

1. **路径删除**（`git filter-repo --invert-paths`）：
   `docs/dsh_run/`、`docs/screenshots/`、`note/`、根级 `SMASS_*.md`。
2. **内容脱敏**（`git filter-repo --replace-text`）：
   把历史中残留的非公开 `django-insecure-*` 字面量替换为
   `django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE`；
   用"哨兵保护"确保两处**允许的公开 dev 默认值**不被误替换。

### 提交数变化

| | 数量 |
|---|---|
| 原始提交（全 refs） | 99 |
| 净化后提交 | 70 |
| 差异原因 | 仅改动禁用路径的提交被删除；其余提交内容并入净化历史 |

---

## 4. 不合规文件清理统计

| 类别 | 数量 | 体积 | 处置 |
|---|---|---|---|
| B 类迁移（Agent 账本/截图/笔记/提示词） | **97 文件** | 2.38 MB | 移入 `.local/`（逐文件 SHA-256 校验） |
| C 类精简（被新账本取代的旧归档） | 5 文件 | 23 KB | 删除（保留现行版本） |
| D 类删除（`__pycache__`/`.pytest_cache`） | **57 个目录** | 2.66 MB | 删除（可重建） |
| 项目外归档目录 | 1 个（129.5 MB） | — | 压缩后迁入 `.local/git-backups/protected/`，原目录删除 |
| 历史中移除的路径 | 4 类前缀 + 1 模式 | — | `filter-repo` 重写 |

### 移动明细（节选）

| 原路径 | 新路径 |
|---|---|
| `docs/dsh_run/` | `.local/agent-sessions/dsh_run/` |
| `docs/screenshots/` | `.local/screenshots/` |
| `note/` | `.local/development-logs/note/` |
| 根级 `SMASS_*.md`（16 个） | `.local/prompts/archive/` |
| 当前治理提示词 | `.local/prompts/active/` |

---

## 5. 本地 `.local/` 归档完整性

| 子目录 | 内容 | 状态 |
|---|---|---|
| `prompts/active` + `archive` | 17 个提示词（当前 + 历史） | 完整 |
| `agent-sessions/dsh_run` | 40 个账本/状态/恢复点文件 | 完整 |
| `screenshots` | 37 个过程截图（1.8 MB） | 完整 |
| `development-logs/note` | 3 个早期开发笔记 | 完整 |
| `git-backups/protected` | 2 bundle + 3 tar.gz + 证据 + SHA-256 清单（79.1 MB） | 完整 |
| `manifests` | RH0/RH1/RH2/RH6/RH9/SHA 映射等 12 个清单 | 完整 |
| `repo-governance` | 治理脚本（扫描/净化/校验/映射） | 完整 |
| `temporary` | 验证用克隆与演练目录 | 可再生，已登记 |

- `.local/` 在 Git 中**0 个跟踪文件**（`git ls-files .local` 为空）。
- 备份可恢复性已验证：从 `raw_snapshot.tar.gz` 解出 `manage.py` 与工作区哈希一致；
  两个 bundle 均 `git bundle verify` → `okay`。

---

## 6. 新旧 SHA 映射（安全摘要）

| ref | 原始 SHA（本地） | 净化 SHA（远端） |
|---|---|---|
| `feat/smass-r11-r20-full-campus` | `c51c61266e` | `55150fce97` |
| `feat/smass-r4-r10-integrated-platform` | `82013b63a9` | `7e6ff5b740` |
| `feat/smass-r3-cutover-hardening` | `7df6e19bc6` | `d20889b846` |
| `feat/smass-r21-account-rbac` | `b527cba8f1` | `46e22e0f7e` |
| `feat/smass-r22-account-cutover` | `57e5963529` | `c0cbaf93f5` |
| `feat/smass-r22-final-hardening` | `f9a99dd416` | `5eef680359` |
| `feat/smass-r22-g6-g8-readiness` | `d24b7867a2` | `0beb5556e7` |
| `feat/smass-r221-release-readiness` | `5b4541246a` | `fca642a7f7` |
| `feat/smass-r15-r20-hardening` | `13fd95f8ff` | `0a73bbd190` |
| `main` | `84e290b585`（后被治理提交推进到 `c51c612`） | `55150fce97` |
| `archive-r3-20261028` | `9c158a00e3` | `9a70cd6471` |

- 提交级映射：99 条原始提交中 **99 条已对齐**（含并入净化历史的条目），
  完整明细见 `.local/manifests/SHA_MAPPING_SANITIZED.json`。
- 映射说明：净化改变了所有被重写提交的 SHA；**内容等价**由文件树哈希与回归结果双重佐证。

---

## 7. 远端全新克隆恢复结果

| 检查 | 结果 |
|---|---|
| 克隆来源 | `https://github.com/MoRanzhi1203/smass-smart-campus.git`（本轮全新目录） |
| HEAD | `55150fce976f7674a2467246853451639065e8a1` |
| 分支 | `main`（与远端 API 一致） |
| 文件数 | **5119** |
| 可见分支 | 10（`origin/HEAD → origin/main`） |
| 可见标签 | 1（`archive-r3-20261028`） |
| `.local/`、`docs/dsh_run/`、`docs/screenshots/`、`note/` | **均不存在** |
| `.env` | 不存在（凭据不入库，符合预期） |
| 关键文件（R11/R16/S25/迁移/准入脚本） | **全部存在**（16 项逐项校验） |
| 准入检查 `--selftest` | **PASS**（14 条必拦 + 10 条必放） |
| 准入检查 `--head` | **PASS**（index 5119 / head 5119，0 问题） |

### 检查范围之外（不宣称已清除）

- GitHub 服务端的**悬空对象缓存**：删除 refs 后对象可能短期保留，需平台侧 GC；
  本报告只声明**受控 refs 与其可达历史**已净化。
- 其他克隆、PR 隐藏 refs（`refs/pull/*`）、Fork、第三方镜像、CI 缓存、备份系统：
  不在本次可验证范围，**不声称已被物理清除**。
- 已泄漏密钥的**有效性**：净化只移除历史痕迹，不能使已外泄的密钥变安全。
  该密钥已在代码层停用（环境注入 + 兼容默认关闭），如需彻底作废需轮换
  （属运维动作，未在本轮执行）。

---

## 8. Django 与迁移检查（净化克隆内）

| 检查 | 结果 |
|---|---|
| Python / Django | 3.12.16 / 5.2.17 |
| `requirements.txt` | 存在（5 条依赖） |
| `manage.py check`（11 个 settings） | **全部 exit 0，no issues** |
| `makemigrations --check --dry-run`（r4/r5/r10/r11/r16） | **No changes detected**（迁移与模型一致） |
| 正式库迁移 | **未执行**（正式 `smass` 保持只读） |

`.env` 由 `smass/env_loader.py` 从项目根加载；克隆缺失时 Django 仍可 `check`，
仅数据库连接不可用——这是"凭据不入库"的预期结果。功能验证时使用本地隔离
`.env`（已被 `.gitignore` 忽略，未提交）。

---

## 9. 全量回归测试结果

命令：`python scripts/r10_full_regression.py --json`（在净化克隆中执行）

| 套件 | settings | 用例 | 结果 | 耗时 |
|---|---|---|---|---|
| `smass_operations` | `settings_r10` | 419 | OK | 412.9s |
| `smass_analytics` | `settings_r7` | 31 | OK | 44.0s |
| `smass_organization` | `settings_r4` | 69 | OK | 72.9s |
| `smass_data_exchange`（roundtrip+ui） | `settings_r4` | 60 | OK | 35.4s |
| `smass_data_exchange`（r5 adapters） | `settings_r5` | 25 | OK | 30.9s |
| `smass_academic` | `settings_r5` | 56 | OK | 107.9s |
| `smass_facilities` | `settings_r16` | 42 | OK | 73.0s |
| `smass_scheduling` | `settings_r11` | 40 | OK | 52.4s |
| `smass_workflow` | `settings_r6` | 41 | OK | 34.0s |
| `smass_api` | `settings_r8` | 23 | OK | 18.3s |
| `r22_account` | `settings_r22` | 117 | OK | 66.8s |
| `r21_account` | `settings_r21` | 110 | OK | 92.8s |
| `app01` | `formal` | 163 | OK | 96.5s |
| `tests_e2e` | `formal` | 16 | OK | 51.5s |
| **合计** | 14 套件 | **1212** | **0 失败** | 约 20 分钟 |

- 退出码 **0**，`all green = True`。
- 与治理前基线（1212 例 / 14 套件）**一致**：治理未破坏任何业务模块。
- 本次运行前已清理残留 `test_*` 数据库（实测 0 个）并确认无残留测试进程，
  避免"0 用例快速失败"的假象。
- 本轮 `tests_e2e`（含 WebKit 用例）16 例全部通过，**未出现**此前记录的
  间歇性导航超时，因此无需触发根因分类流程。

---

## 10. 正式数据库前后指纹比较

| 指标 | 回归前 | 回归后 |
|---|---|---|
| 数据库 | `smass` | `smass` |
| 表数量 | 26 | 26 |
| 列数量 | 111 | 111 |
| `schema_sha256` | `014a5e13…` | `014a5e13…` |
| `tables_sha256` | `8a2b495d…` | `8a2b495d…` |
| `rows_sha256` | `057a5466…` | `057a5466…` |
| **combined** | `b914b39cc7ec9469b1ac925dfa526d4f8c58bd9283fcfdad0a834bedaee106e3` | **同一值** |

结论：**正式库零写入**。未执行 migrate / flush / 任何写操作。

---

## 11. 44 项研发任务账本状态

| 项 | 值 |
|---|---|
| 账本位置（治理后） | `.local/agent-sessions/dsh_run/SMART_CAMPUS_MASTER_TASKS.json` |
| 任务总数 | **44** |
| `TESTED` | **12** |
| `PENDING` | **32** |

`TESTED` 清单：`G0`、`S0`、`S01`、`S02`、`S03`、`S06`、`S25`、`S25-R4`、`S25-R5`、
`R16-RESOURCE`、`R11`、`R11-UI`。

- 治理过程**未修改**任何任务状态、未新增/删除任务 ID、未改动证据路径语义。
- 为保持门禁可运行，只把脚本的账本目录改为"优先 `.local/`、回退 `docs/dsh_run/`"，
  并为 `evidence_paths` 增加只读重定向；账本文件本身逐字未改。
- 仓库治理作为**独立验收**（本报告），不占用 44 项研发任务额度。

---

## 12. 已知限制与待处理问题

| 编号 | 事项 | 影响 | 计划 |
|---|---|---|---|
| L-1 | GitHub 免费私有仓库不支持分支/标签保护（403） | 无法防强推 | 依赖不可变 SHA + 准入脚本；升级套餐后可开启 |
| L-2 | 净化后 SHA 全部改变 | 外部引用旧 SHA 会失效 | 用本报告与 `.local` 映射表对接 |
| L-3 | 已泄漏的历史 MD5 密钥**未轮换** | 旧密钥仍可能有效 | 需运维执行密钥轮换；代码层已停用兼容 |
| L-4 | GitHub 悬空对象、其他克隆未被物理清除 | 理论上仍可能被恢复 | 已声明范围；如需彻底清除需平台支持 |
| L-5 | `docs/SMASS_*` 历史技术报告保留在库中 | 体积与可读性 | 属"有维护价值文档"，按规则保留 |
| L-6 | `.local/temporary` 含验证克隆（约 83 MB） | 占用磁盘 | 可随时删除，不影响 Git 与恢复链 |
| L-7 | 三个早期归档分支（r21/r22 系列）内容相近 | 分支冗余 | 属历史节点，未删除；可在后续治理中合并 |
| L-8 | WebKit 间歇性超时 | 偶发 E2E 波动 | 本轮未复现；已保留诊断开关 `R10_H3_TIMEOUT_MS` |

---

## 13. 最终 Git 状态

### 本地原始仓库（唯一工作区，**未被直接重写**）

| 项 | 值 |
|---|---|
| 路径 | 项目根目录 |
| 分支 | `feat/smass-r11-r20-full-campus` |
| HEAD | `c51c61266ea90cde8f6ad00523e42c85c3717d44` |
| 工作区 | 干净（0 个未提交改动，本轮所有变更已提交） |
| 远端 | 未配置（推送统一经由独立镜像完成，避免误推原始历史） |

### 远端（净化后）

| 项 | 值 |
|---|---|
| `main` | `55150fce976f7674a2467246853451639065e8a1` |
| `feat/smass-r11-r20-full-campus` | 同上（完全一致） |
| 分支数 / 标签数 | 10 / 1 |
| 默认分支 | `main` |

### 本轮新增提交（原始仓库）

| 提交 | 内容 |
|---|---|
| `c51c612` | RH2–RH4：本地资料迁入 `.local`、准入检查、公开技术文档 |
| 本轮最终提交 | RH9–RH10：最终报告与验收证据（见 `git log -1 --format=%H`） |

---

## 14. 复现命令（治理后）

```bash
# 1) 仓库准入（提交前）
python scripts/repo_admission_check.py --selftest
python scripts/repo_admission_check.py
python scripts/repo_admission_check.py --head

# 2) 环境自检
python manage.py check --settings=smass.settings_r11
python manage.py makemigrations --check --dry-run --settings=smass.settings_r11

# 3) 全量回归（约 20 分钟，14 套件）
python scripts/r10_full_regression.py --json

# 4) 正式库只读指纹
python scripts/db_fingerprint.py
```

> 研发账本与过程证据位于 `.local/`（不进入版本库）。克隆仓库后若要恢复
> 研发上下文，需从受保护备份单独取回，这不影响工程本身的可构建性。

---

## 附录 A：与其他文档的关系

| 文档 | 作用 |
|---|---|
| `docs/SMASS_Technical_Decisions.md` | 公开技术决策（身份、容量、授权、排课、S25、R16） |
| `docs/SMASS_GitHub_Archive_Report.md` | G0 归档阶段报告（早期，仅字节脱敏） |
| 本报告 | RH0–RH10 治理与净化的最终验收 |

## 附录 B：诚实性声明

- 本报告所有数字均来自**实际执行输出**，未按预期值回填。
- 未声称"GitHub 缓存已物理清除""其他克隆已失效"。
- 未声称"密钥已失效"——只声明代码层停用，轮换属运维动作。
- 未将仓库治理计入 44 项研发任务的完成数。
- 未删除、跳过或改写任何失败测试；本轮回归 0 失败是实测结果。
