# R17 校内论坛、公告、举报与内容管理

> 状态：**TESTED**（32 例：服务 21 + 页面 10 + Chromium E2E 1）
> 代码：`smass_forum/`、`templates/r17/`、`smass/settings_r17.py`、`smass/urls_r17.py`
> 隔离库：`smass_r17_forum`

## 1. 验收项与实现对应

| 验收项 | 实现 | 测试 |
|---|---|---|
| 板块与帖子 | 板块可创建（管理员）；发帖校验标题/正文/板块状态 | `test_create_board_permission`、`test_empty_title_rejected`、`test_archived_board_rejected` |
| 评论 | 仅正常帖子可评论；下架后不可评论 | `test_comment_and_hidden_post` |
| 内容处置 | 作者可下架自己的内容；删除仅版主/管理员；removed 为终态 | `test_author_can_hide_own_post`、`test_other_cannot_hide`、`test_moderator_can_remove`、`test_removed_is_terminal` |
| 举报 | 任何登录用户可举报帖子/评论；重复举报拒绝；理由必填 | `test_report_and_hide`、`test_duplicate_report_rejected`、`test_empty_reason_rejected` |
| 举报处理 | 下架/删除/驳回三选一；处理人与时间留痕；只能处理一次 | `test_dismiss_report_keeps_content`、`test_non_moderator_cannot_resolve`、`test_resolve_twice_rejected` |
| 可见性 | 下架内容仅作者与版主可见；删除内容对所有人不可见 | `test_author_sees_hidden_others_do_not`、`test_removed_hidden_even_for_author` |
| 公告 | 管理员创建草稿 → 发布；未发布对学生不可见；受众过滤 | `test_draft_not_visible_to_student`、`test_published_visible`、`test_audience_filter` |
| 页面流程 | 发帖/评论/举报/处理/公告全部页面可用 | `test_student_creates_post_and_comment`、`test_student_reports_and_admin_resolves`、浏览器 E2E |

## 2. 设计要点

- **不做物理删除**：内容只有 `published/hidden/removed` 三态，保留审计与追溯；
- **举报与处置原子化**：`resolve_report` 在事务内锁举报行，先更新内容状态再更新举报状态，
  避免"举报已处理但内容没动"；
- **可见性默认最小**：普通用户只看正常内容 + 自己的下架内容；删除内容对作者也不可见；
- **XSS**：正文在模板中自动转义，`white-space:pre-wrap` 保留换行，不渲染 HTML。

## 3. 测试命令与实测结果

```powershell
$py = "C:\Users\MSIPC\.conda\envs\smass\python.exe"
& $py manage.py test smass_forum --settings=smass.settings_r17
```

实测（2026-10-30）：**32 例 OK**（服务 21 + 页面 10 + Chromium E2E 1）。

## 4. 已知边界

1. 未实现富文本/Markdown 与图片上传（安全文件上传在 S14，接入后再开放附件）；
2. 未实现敏感词自动过滤与 AI 审核，只有人工举报 + 版主处置；
3. 举报处理不通知举报人（通知能力待 S12 通知服务统一）；
4. 公告无定时发布与置顶排序（可后续在 `Announcement` 加字段扩展）。
