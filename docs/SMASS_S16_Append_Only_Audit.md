# S16 追加式审计与安全告警

> 状态：**TESTED**（20 例：服务 16 + 页面 4 + Chromium E2E 1）
> 代码：`smass_audit/`、`templates/s16/`、`smass/settings_s16.py`、`smass/urls_s16.py`
> 隔离库：`smass_s16_audit`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 追加式审计 | `AuditEvent.save/delete` 对已存在记录抛错 | `test_append_only` |
| 哈希链 | `hash = SHA256(prev_hash + 规范化字段)`，逐条链接 | `test_chain_links` |
| 篡改检测 | `verify_chain()` 返回首个断链位置 | `test_tamper_detected`、`test_admin_sees_chain_status` |
| 冲突/特权告警 | 窗口内 denied 次数 ≥ 阈值生成告警；严重度按倍数升级 | `test_threshold_creates_alert`、`test_below_threshold_no_alert` |
| 告警幂等 | 同主体同窗口只保留一条待处理告警 | `test_alert_is_idempotent_in_window` |
| 告警处置 | 管理员确认，重复确认拒绝 | `test_acknowledge`、`test_scan_creates_alert_and_ack` |
| 权限 | 普通账号只看自己的事件；告警仅审计管理员可见 | `test_student_sees_own_events`、`test_student_forbidden_on_alerts`、`test_student_cannot_acknowledge` |
| 输入校验 | 空动作、非法结果码拒绝 | `test_bad_input` |

## 2. 设计要点

- **规范化 payload**：`json.dumps(sort_keys=True, separators=(',',':'))` 保证同一事件哈希可复现；
- **链校验只读**：`verify_chain` 不改数据，任意一条被 `UPDATE` 篡改都会断链；
- **告警去重**：按 `(alert_type, subject, status=open, 窗口)` 判重，避免刷屏；
- **数据范围**：事件按 `actor_id` 收敛，告警只对审计管理员开放。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_audit --settings=smass.settings_s16
```

实测（2026-10-30）：**20 例 OK**（服务 16 + 页面 4 + Chromium E2E 1）。

## 4. 已知边界

1. 哈希链是应用层防篡改，生产应叠加数据库权限隔离（审计账号只 INSERT）与外部 WORM 存储；
2. 告警检测为**按需扫描**，未实现实时流式检测（可由定时任务调用 `detect_alerts`）；
3. 未实现跨模块自动埋点（各模块需显式调用 `services.record`），
   后续可在中间件层统一记录拒绝事件；
4. 链校验为全表线性扫描，数据量大时需分批校验或定期锚定（Merkle 根）。
