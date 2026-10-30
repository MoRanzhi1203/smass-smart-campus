# S24 发布门禁

> 状态：**TESTED**（一键门禁 11 项，干净工作区实测 PASS）
> 脚本：`scripts/s24_release_gate.py`
> 证据：`.local/evidence/s24/s24_gate.json`

## 1. 门禁项与判定

| # | 检查 | 判定标准 | 失败含义 |
|---|---|---|---|
| 1 | `git-clean` | 工作区无未提交改动 | 有未提交代码，不可发布 |
| 2 | `git-remote-sync` | HEAD == `origin/<branch>` | 本地与远端不一致 |
| 3 | `admission` | `repo_admission_check.py` PASS | 仓库准入不合规（大文件/敏感路径等） |
| 4 | `secret-scan` | `r9_secret_scan.py` PASS | 存在疑似凭据 |
| 5 | `deps` | `s20_dependency_audit.py` PASS | 锁定/基线/一致性不达标 |
| 6 | `controls` | `s21_incident_drill.py --matrix-only` PASS | 安全控制点缺失 |
| 7 | `migrations` | `makemigrations --check` 无变更 | 模型改了但没生成迁移 |
| 8 | `security-suite` | S18 负向测试集全过 | 跨模块安全回归失败 |
| 9 | `session-suite` | S17 会话安全测试全过 | 会话/设备管理回归失败 |
| 10 | `mfa-suite` | S09 特权 MFA 测试全过 | MFA 回归失败 |
| 11 | `ledger` | 账本无 `BLOCKED`（只报告） | 有阻塞任务或账本损坏 |

任一 `fail` → 门禁 **FAIL**（退出码 1）；`skip` 不影响结论但会标注。

## 2. 使用方法

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"

# 完整门禁（发布前必须跑）
& $py scripts\s24_release_gate.py --json .local\evidence\s24\s24_gate.json

# 本地快检（跳过三个测试套件）
& $py scripts\s24_release_gate.py --quick

# 开发中允许脏工作区
& $py scripts\s24_release_gate.py --allow-dirty

# 追加联网漏洞扫描（较慢）
& $py scripts\s24_release_gate.py --with-pip-audit

# 门禁自身自检
& $py scripts\s24_release_gate.py --self-test
```

## 3. 本次实测（2026-10-31，干净工作区）

| 检查 | 结果 |
|---|---|
| git-clean | PASS |
| git-remote-sync | PASS（本地 = 远端 = `bfa2a75`，提交后复跑一致） |
| admission | PASS |
| secret-scan | PASS（白名单 11 项，测试夹具 108 处已识别） |
| deps | PASS |
| controls | PASS（10/10 控制点） |
| migrations | PASS（无未生成迁移） |
| security-suite | PASS（20 例） |
| session-suite | PASS（19 例） |
| mfa-suite | PASS（24 例） |
| ledger | PASS（TESTED 41 / PENDING 3） |
| **GATE** | **PASS** |

脚本自检：5 项 PASS。

## 4. 本轮修复的真实问题

1. **子进程输出按 GBK 解码导致 `UnicodeDecodeError`**：`subprocess.run(text=True)` 在中文 Windows
   默认用系统 locale 解码，而脚本输出是 UTF-8 中文。已在 S21/S22/S23/S24 四个脚本统一加
   `encoding='utf-8', errors='replace'`。
2. **账本路径算错**：`ROOT.parent / '.local' / ...` 多了一层，导致 `ledger` 恒为 `skip`。
   修正为 `ROOT.parent / 'agent-sessions' / ...` 后能真实统计。

## 5. CI 集成建议

```yaml
# 伪代码：在 CI 中作为唯一放行入口
- run: python scripts/s24_release_gate.py --json gate.json
- uses: actions/upload-artifact@v4
  with: { name: release-gate, path: gate.json }
```

发布流程建议：`s24 门禁 PASS` → `打 tag` → `部署` → `部署后跑 /s19/ 与 /r21/home/ 冒烟`。

## 6. 已知边界

1. 门禁跑的是**测试库**，不验证生产数据与正式库结构（正式库只读指纹在 FINAL 单独执行）；
2. 未接入代码签名/镜像扫描（容器化后再补）；
3. `--quick` 会跳过三个安全测试套件，仅限本地开发使用，**发布禁止 `--quick`**；
4. 门禁不检查浏览器 E2E 全量（各模块的 Chromium 用例在 REGRESSION 阶段跑）。
