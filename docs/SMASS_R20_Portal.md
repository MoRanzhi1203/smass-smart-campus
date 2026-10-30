# R20 多角色统一门户

> 状态：**TESTED**（26 例：服务 18 + 页面 6 + Chromium E2E 2）
> 代码：`smass_portal/`、`templates/r20/`、`smass/settings_r20.py`、`smass/urls_r20.py`
> 隔离库：`smass_r20_portal`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 学生门户 | `student` 区块：学籍异动、转专业、考勤、活动、社团、论坛、账单 | `test_student_sees_only_student_section`、`test_admin_bootstrap_then_student_sees_portal` |
| 教师/辅导员门户 | `teacher` 区块：考勤、活动、社团、论坛、专项组织 | `test_teacher_sees_teacher_section`、`test_teacher_sees_teacher_portal` |
| 管理人员门户 | `admin` 区块（学院/系统管理员）：分班、考勤统计、活动认定、干部、举报、台账、审计 | `test_admin_sees_admin_section` |
| 无角色默认拒绝 | 无任何角色 → 门户空，不泄露入口 | `test_no_role_sees_nothing`、`test_empty_account_context` |
| 链接角色过滤 | 同一区块内链接可单独限定角色 | `test_links_filtered_by_role` |
| 链接解析 | 优先 `reverse(url_name)`，失败回退 `fallback_url`，再失败 `#` | `test_reverse_works`、`test_invalid_name_falls_back`、`test_no_target_returns_hash` |
| 公告 | 草稿对学生不可见；发布后按角色可见；管理员可见草稿 | `test_draft_hidden_from_student`、`test_role_filtered_notice`、`test_admin_sees_drafts` |
| 配置权限 | 只有学院/系统管理员可配置；学生 403 | `test_student_cannot_create`、`test_student_forbidden_on_admin` |
| 默认初始化 | 幂等创建三套门户与欢迎公告 | `test_bootstrap_is_idempotent`、`test_admin_creates_section_and_link` |

## 2. 设计要点

- **数据驱动**：门户 = 区块 + 链接 + 公告，管理员可在 `/r20/admin/` 配置；
- **不强耦合其他模块**：链接用 Django URL 名解析，失败回退固定路径，
  因此门户可单独部署、逐模块上线；
- **角色是唯一可见性依据**：`roles` 逗号分隔，空角色一律看不到；
- 默认门户覆盖 R12/R13/R14/R15/R17/R18/R19 的入口，真实可用。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_portal --settings=smass.settings_r20
```

实测（2026-10-30）：**26 例 OK**（服务 18 + 页面 6 + Chromium E2E 2）。

## 4. 已知边界

1. 门户未聚合"待办数量"（待审请假、待处理举报等），需要跨模块统计 provider，
   待各模块提供计数接口后再接入；
2. 未实现用户自定义布局/收藏（需前端状态与用户偏好表）；
3. 链接权限只按角色，不含"学院范围"细分（可在 `PortalLink` 增加 scope 字段扩展）；
4. 门户不承载单点登录跳转，仍走各模块自身的 `/r21/login/` 会话。
