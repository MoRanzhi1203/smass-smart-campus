# R15 团委、学生会、学生社团与干部任职

> 状态：**TESTED**（28 例：服务 20 + 页面 7 + Chromium E2E 1）
> 代码：`smass_clubs/`、`templates/r15/`、`smass/settings_r15.py`、`smass/urls_r15.py`
> 隔离库：`smass_r15_clubs`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 组织建模 | `Club` 自引用上级，类别：团委/学生会/社团/协会 | `test_create_club`、`test_bad_category` |
| 组织创建与归档 | 仅教师/管理员；归档后不能加入 | `test_student_cannot_create`、`test_archive_blocks_join` |
| 成员申请与审批 | 申请 → 待审 → 在册；重复申请拒绝；驳回必填原因 | `test_apply_and_approve`、`test_duplicate_application`、`test_reject_requires_reason` |
| 权限边界 | 只有本组织负责人或管理员可审批；学生会/社团负责人可操作本组织 | `test_non_leader_cannot_approve`、`test_leader_approves_via_page` |
| 退出与重新加入 | 退出保留历史，重新加入复用记录并回到待审 | `test_leave_and_rejoin` |
| 负责人设置 | 在册成员可提升/取消负责人 | `test_promote_and_demote` |
| 干部任职 | 必须是本组织在册成员；职务 + 任期建模；卸任保留历史 | `test_appoint_and_end`、`test_non_member_cannot_be_appointed` |
| 任职唯一性 | 主席/副主席/书记每组织每任期唯一；部长可多人 | `test_duplicate_post_taken`、`test_unique_posts_conflict`、`test_minister_allows_multiple` |
| 卸任释放名额 | 卸任后可重新任命 | `test_end_post_frees_slot` |
| 页面范围 | 学生只看自己的成员与任职；负责人可见全部以便审批 | `test_student_sees_only_own_membership`、`test_posts_page_lists_own_posts` |

## 2. 设计要点

- **成员身份与职务解耦**：`ClubMembership` 记录成员关系，`ClubPost` 记录职务与任期；
  卸任不影响成员身份，退会不自动删除历史任职；
- **任职唯一性在行锁内校验**：MySQL 不支持条件唯一约束，`appoint_post` 对 `Club`
  行加锁后再检查，保证并发任命不会出现两个主席；
- **负责人权限是对象级**：负责人只能管理自己所在组织，不是全局角色；
- 权限白名单与 R13/R14 一致（teacher/college_admin/system_admin）。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_clubs --settings=smass.settings_r15
```

实测（2026-10-30）：**28 例 OK**（服务 20 + 页面 7 + Chromium E2E 1）。

## 4. 已知边界

1. 干部任期用自由文本（如 `2026-2027`），未与 R11 学年模型强绑定；
2. 未实现"社团年审/星级评定/指导教师审批"等团委专项流程（需学校政策输入）；
3. 成员退出不自动撤销其未卸任职务（需负责人显式卸任或管理员处理）；
4. 通知与公示（拟任公示期）未实现，留待 S12 通知与 R17 公告能力整合。
