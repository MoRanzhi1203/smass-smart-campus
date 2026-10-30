# S07 密钥与配置管理（验收报告）

- 配置：`smass/settings.py`、`.env.example`、`.gitignore`
- 扫描：`scripts/r9_secret_scan.py`
- 回归：`app01/tests/test_s07_secret_config.py`（6 例）

## 1. 验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| 各环境配置分离且无凭据入库 | PASS | `.env` 被忽略；`.env.example` 仅占位符 |
| DEBUG/HOSTS/COOKIE/CSRF 安全默认 | PASS | `test_production_defaults_enabled` |
| 最小权限与轮换计划文档 | PASS | 本文 §4、§5 |
| 全量变更秘密扫描通过 | PASS | `[PASS] 未发现生产凭据（白名单 11 项；测试夹具 58 处已识别）` |

## 2. 生产 fail-fast

```python
DEBUG = env_bool('DJANGO_DEBUG', True)
SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE'
    else:
        raise RuntimeError('生产模式必须通过 DJANGO_SECRET_KEY 提供密钥')
```

实测：`DJANGO_DEBUG=False` 且未提供 `DJANGO_SECRET_KEY` 时进程直接失败，
错误信息指向环境变量名，不会以开发默认值启动。

## 3. 安全默认

`DEBUG=False` 时自动启用：

| 设置 | 值 |
|---|---|
| `SESSION_COOKIE_SECURE` | True |
| `CSRF_COOKIE_SECURE` | True |
| `SECURE_CONTENT_TYPE_NOSNIFF` | True |
| `SECURE_REFERRER_POLICY` | `same-origin` |
| `SESSION_COOKIE_HTTPONLY` | True（始终） |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | `Lax` |
| `X_FRAME_OPTIONS` | `DENY` |

SSL 重定向、HSTS 默认关闭（0），需要部署方按域名与证书情况显式开启：
`DJANGO_SECURE_SSL_REDIRECT`、`DJANGO_SECURE_HSTS_SECONDS`、
`DJANGO_BEHIND_PROXY`。

## 4. 轮换计划

| 凭据 | 当前状态 | 计划 |
|---|---|---|
| Django `SECRET_KEY` | 本地开发为占位；生产未部署 | 上线前由运维生成 ≥50 字节随机值并托管；轮换会使会话失效，需在维护窗口执行 |
| 数据库口令 | 仅本地 `.env`，未入库 | 生产使用最小权限账号（仅所需库的 SELECT/INSERT/UPDATE/DELETE，DDL 走迁移账号） |
| 旧 MD5 密钥 | 已从受控 Git 历史清除，**未完成运维退役** | 见 §5 |
| API Token | `smass_api` 存 sha256 摘要 | 支持显式吊销；轮换需签发新 token 并吊销旧 token |

## 5. 旧 MD5 密钥风险与处置（未授权项）

事实：

- 旧 MD5 密钥已从受控 Git 历史删除，但**外部副本/缓存无法证明已清除**；
- 代码层已停用：`verify_password` 在未注入 `SMASS_LEGACY_MD5_SECRET_KEY`
  时拒绝所有 legacy 哈希（S01 遏制）；
- 本轮**没有**修改任何真实用户密码或生产密钥（未授权）。

处置方案（需运维/校方授权后执行）：

1. 保持 `SMASS_LEGACY_MD5_SECRET_KEY` 不注入；仅在受控迁移窗口短时启用；
2. 对仍使用 32 位 MD5 的账号强制重置密码（S02 生命周期已具备）；
3. 轮换后监控 `legacy_md5_rejected reason=secret_not_injected` 日志是否为 0；
4. 在密钥管理系统（Vault/KMS）中登记新密钥，禁止再次写入代码或 `.env`。

## 6. 扫描器行为

- 扫描 git 跟踪的文本文件（`.py/.md/.yml/.json/.html/.ps1/...`）；
- 命中私钥块、AWS key、硬编码 password/token、长 Bearer；
- 测试夹具与开发占位符标记为 `TEST_FIXTURE` 而不是 `ISSUE`，
  保持可见但不会阻断；
- 任何 `ISSUE` 都会使命令返回非零。

## 7. 未完成

| 项 | 状态 | 原因 |
|---|---|---|
| 密钥托管服务接入 | 未实现 | 需要生产 KMS/Vault 与网络授权 |
| 自动轮换 | 未实现 | 需运维平台与密钥管理系统 |
| `check --deploy` 全绿 | 未声明 | HSTS/SSL 需按真实域名与证书配置 |
