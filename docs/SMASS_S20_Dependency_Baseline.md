# S20 依赖锁定与补丁基线

> 状态：**TESTED**（脚本自检 10 项 + 5 项审计检查全 PASS，pip-audit 联网实测）
> 产物：`requirements.lock.txt`（项目依赖精确锁定）、`scripts/s20_dependency_audit.py`
> 证据：`.local/evidence/s20_dependency_audit.json`、`.local/evidence/s20_env_snapshot.txt`

## 1. 做了什么

1. **精确锁定项目依赖**：从白名单闭包生成 `requirements.lock.txt`，15 个包全部 `==`：

   | 类别 | 包 |
   |---|---|
   | Web 框架 | Django 5.2.17、asgiref 3.13.0、sqlparse 0.6.0、tzdata 2026.5、django-cors-headers 4.9.0 |
   | 数据库 | PyMySQL 1.1.2、cryptography 50.0.2、cffi 2.1.1、pycparser 3.12 |
   | 文件/导出 | openpyxl 3.1.5、et_xmlfile 2.0.0、pillow 13.0.0 |
   | 浏览器 E2E | playwright 1.64.1、greenlet 3.5.6、pyee 14.0.0 |

2. **审计脚本**（可离线运行）：
   - `all-pinned`：锁文件必须全部 `==`；
   - `reproducible`：不得出现 `+cpu` 之类本地版本后缀；
   - `security-baseline`：Django/PyMySQL/cryptography/sqlparse/Pillow/playwright 达到最低安全版本；
   - `lock-matches-env`：锁定版本与当前解释器实际安装一致；
   - `pip-audit`：联网漏洞扫描（失败时 `warn`，不伪造通过）。

3. **环境快照**：`pip freeze` 的 97 个包另存为 `requirements.env-snapshot.txt`
   （仅本地证据、已 `.gitignore`），便于回溯本次审计的环境原貌。

## 2. 实测结果（2026-10-30）

```
[PASS] all-pinned             全部精确锁定
[PASS] reproducible           无本地版本后缀
[PASS] security-baseline      关键包均达到基线
[PASS] lock-matches-env       锁与环境一致
[PASS] pip-audit              未发现已知漏洞
RESULT: PASS
```

项目依赖 15 个、环境包 97 个、被排除的环境残留 82 个。

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py scripts\s20_dependency_audit.py --self-test
& $py scripts\s20_dependency_audit.py --json .local\evidence\s20_dependency_audit.json
```

## 3. 审计过程中的真实发现（已记录，未隐藏）

1. **`torch==2.12.0+cpu` 导致 pip-audit 无法解析**：该包是本地 CPU 轮子、PyPI 无对应分发，
   全量环境快照直接审计会失败。处理：项目锁定只保留运行依赖闭包，快照单独留存。
2. **`requirements.web.lock.txt` 中文注释导致 `UnicodeDecodeError`**：`pip-audit`
   在 Windows 下按系统 locale（GBK）解码 requirements 文件。处理：锁文件注释改为纯 ASCII，
   并在脚本注释中固化该约束。
3. **环境快照中存在带已知漏洞的包 `pypdf 6.13.1`**（30+ 条 PYSEC/CVE，修复版本最高 6.21.2）：
   经检索项目代码 **0 处引用 pypdf**，判定为非 SMASS 运行依赖（本机环境残留）。
   **若该环境还服务其他项目，应将 pypdf 升级到 ≥ 6.21.2**；SMASS 自身不受其影响。
4. **`requirements.txt` 的顶层依赖未锁定**（`PyMySQL>=1.1.2,<2`、`cryptography>=41,<51`）：
   本轮以 `requirements.lock.txt` 补足可复现性，原文件保留历史语义。

## 4. 已知边界

1. 未生成 SBOM/签名验证（如需合规可加 `cyclonedx-py` 输出 CycloneDX 报告）；
2. pip-audit 依赖联网访问 OSV/PyPI，离线环境只会得到 `warn`，不会假装通过；
3. 锁定仅覆盖 Python 侧；MySQL 8.0.18 服务端补丁与 Windows 主机补丁不在本项范围（见 S22/S24）；
4. `requirements.env-snapshot.txt` 含本机无关包（torch/transformers 等），不得直接部署到服务器。
