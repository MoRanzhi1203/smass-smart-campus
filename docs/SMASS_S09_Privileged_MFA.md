# S09 特权角色多因素认证（TOTP）

> 状态：**TESTED**（24 例：服务 18 + 页面 5 + Chromium E2E 1）
> 代码：`smass_mfa/`、`templates/s09/`、`smass/settings_s09.py`、`smass/urls_s09.py`
> 隔离库：`smass_s09_mfa`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| TOTP 算法 | 纯标准库实现 RFC 6238（HMAC-SHA1 / 30s / 6 位） | `test_rfc_vector`（T=59 → 287082） |
| 验证窗口 | 允许 ±1 个时间片，150 秒外失败 | `test_verify_with_window` |
| 输入校验 | 非数字/长度不符/错误码一律拒绝 | `test_bad_input`、`test_wrong_code_increases_failures` |
| 绑定流程 | `enroll` 生成 Base32 密钥与 otpauth URI → `confirm` 校验并启用 | `test_enroll_and_confirm`、`test_setup_page_shows_secret` |
| 恢复码 | 8 个一次性码，**只存 SHA-256**，明文仅展示一次 | `test_enroll_and_confirm`、`test_recovery_codes_stored_hashed` |
| 恢复码一次性 | 使用一次后失效 | `test_verify_with_recovery_code_once` |
| 重新生成恢复码 | 需当前 TOTP；旧码作废 | `test_regenerate_recovery_codes` |
| 停用保护 | 停用必须提供有效 TOTP/恢复码 | `test_disable_requires_code`、`test_disable_requires_valid_code` |
| 特权强制 | 特权角色未启用 → 强制 `/s09/setup/` | `test_privileged_forced_to_setup`、`test_enroll_and_verify`（浏览器） |
| 二次验证 | 新会话访问业务页 → 强制 `/s09/verify/`，验证后 12 小时内放行 | `test_full_flow_setup_then_verify`、`test_enroll_and_verify`（浏览器） |
| 非特权不受影响 | 学生/教师直接放行 | `test_student_not_affected`、`test_privileged_roles` |
| 策略可配置 | `MFA_ENABLED` / `MFA_REQUIRED_ROLES`；关闭时中间件透明 | `test_disabled_policy` |

## 2. 设计要点

- **中间件策略**：`MfaRequiredMiddleware` 在 `AuthenticationMiddleware` 之后，仅对
  "已登录 + 特权角色 + `MFA_ENABLED`"生效，放行 `/s09/`、登录/退出与静态资源；
- **两段状态**：未绑定 → setup；已绑定但会话未验证 → verify；验证状态写 session
  且 12 小时过期；
- **绑定即验证**：`confirm` 成功后当前会话直接标记已验证（避免刚绑完又被要求验证）；
- **恢复码哈希存储**：`RecoveryCode.save/delete` 禁止修改，消费用 `queryset.update`
  原子置 `used_at`，避免并发重复使用。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_mfa --settings=smass.settings_s09
```

实测（2026-10-30）：**24 例 OK**（服务 18 + 页面 5 + Chromium E2E 1）。

## 4. 已知边界

1. **TOTP secret 当前以 Base32 明文存库**：这是开发/合成基线；生产必须用 KMS/信封加密
   或硬件令牌，且禁止把 secret 写入日志（当前已不写）；
2. 未接入短信/邮件 OTP 与 WebAuthn/FIDO2（可在此模型上扩展 `device_type`）；
3. 未做"连续失败锁定"（只有计数），生产应结合 S23 限流与会话锁定；
4. 未提供管理员代重置 MFA 的流程（需结合 S10 双人审批）。
