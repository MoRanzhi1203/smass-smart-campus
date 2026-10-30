"""R17：校内论坛、公告、举报与内容管理（隔离模块）。

设计约定
--------
1. 内容生命周期：``published`` → ``hidden``（下架，作者可见/管理员可见）→
   ``removed``（删除，保留审计）；不做物理删除；
2. 举报：任何登录用户可举报帖子/评论；管理员处理（下架/删除/驳回），
   处理结果与处理人留痕；
3. 公告：管理员创建并发布，可指定受众（全体/学生/教师）；
4. 所有写操作走服务层；学生只能管理自己的内容，管理员/版主可管理全部。
"""
from __future__ import annotations

from django.db import models

# ---------------------------------------------------------------------------
# 板块
# ---------------------------------------------------------------------------
BOARD_ACTIVE = 'active'
BOARD_ARCHIVED = 'archived'


class Board(models.Model):
    code = models.CharField('编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=64)
    description = models.CharField('简介', max_length=200, blank=True, default='')
    status = models.CharField('状态', max_length=16, default=BOARD_ACTIVE)
    sort_order = models.IntegerField('排序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '论坛板块'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'code']

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


# ---------------------------------------------------------------------------
# 帖子与评论
# ---------------------------------------------------------------------------
CONTENT_PUBLISHED = 'published'
CONTENT_HIDDEN = 'hidden'
CONTENT_REMOVED = 'removed'
CONTENT_STATUS = (
    (CONTENT_PUBLISHED, '正常'),
    (CONTENT_HIDDEN, '已下架'),
    (CONTENT_REMOVED, '已删除'),
)


class Post(models.Model):
    board = models.ForeignKey(
        Board, verbose_name='板块', on_delete=models.PROTECT,
        related_name='posts')
    author = models.ForeignKey(
        'r21_account.Account', verbose_name='作者', on_delete=models.PROTECT,
        related_name='forum_posts')
    title = models.CharField('标题', max_length=120)
    body = models.TextField('正文', max_length=5000)
    status = models.CharField('状态', max_length=16, choices=CONTENT_STATUS,
                              default=CONTENT_PUBLISHED)
    pinned = models.BooleanField('置顶', default=False)
    view_count = models.PositiveIntegerField('浏览数', default=0)
    created_at = models.DateTimeField('发布时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '帖子'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['board', 'status', '-created_at']),
            models.Index(fields=['author', 'status']),
        ]

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(
        Post, verbose_name='帖子', on_delete=models.CASCADE,
        related_name='comments')
    author = models.ForeignKey(
        'r21_account.Account', verbose_name='作者', on_delete=models.PROTECT,
        related_name='forum_comments')
    body = models.CharField('内容', max_length=2000)
    status = models.CharField('状态', max_length=16, choices=CONTENT_STATUS,
                              default=CONTENT_PUBLISHED)
    created_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        verbose_name = '评论'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['post', 'status', 'created_at'])]

    def __str__(self):
        return '{}...'.format(self.body[:20])


# ---------------------------------------------------------------------------
# 举报
# ---------------------------------------------------------------------------
TARGET_POST = 'post'
TARGET_COMMENT = 'comment'
TARGET_TYPES = ((TARGET_POST, '帖子'), (TARGET_COMMENT, '评论'))

REPORT_PENDING = 'pending'
REPORT_RESOLVED = 'resolved'
REPORT_DISMISSED = 'dismissed'
REPORT_STATUS = (
    (REPORT_PENDING, '待处理'),
    (REPORT_RESOLVED, '已处理'),
    (REPORT_DISMISSED, '已驳回'),
)

REPORT_ACTION_HIDE = 'hide'
REPORT_ACTION_REMOVE = 'remove'
REPORT_ACTION_DISMISS = 'dismiss'
REPORT_ACTIONS = (
    (REPORT_ACTION_HIDE, '下架内容'),
    (REPORT_ACTION_REMOVE, '删除内容'),
    (REPORT_ACTION_DISMISS, '驳回举报'),
)


class Report(models.Model):
    target_type = models.CharField('对象类型', max_length=16, choices=TARGET_TYPES)
    target_id = models.PositiveIntegerField('对象 ID')
    reporter = models.ForeignKey(
        'r21_account.Account', verbose_name='举报人', on_delete=models.PROTECT,
        related_name='forum_reports')
    reason = models.CharField('举报理由', max_length=500)
    status = models.CharField('状态', max_length=16, choices=REPORT_STATUS,
                              default=REPORT_PENDING)
    action = models.CharField('处理动作', max_length=16, blank=True, default='')
    handled_by = models.CharField('处理人', max_length=32, blank=True, default='')
    handled_at = models.DateTimeField('处理时间', null=True, blank=True)
    created_at = models.DateTimeField('举报时间', auto_now_add=True)

    class Meta:
        verbose_name = '举报'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return '{}#{} {}'.format(self.target_type, self.target_id, self.reason[:20])


# ---------------------------------------------------------------------------
# 公告
# ---------------------------------------------------------------------------
AUDIENCE_ALL = 'all'
AUDIENCE_STUDENT = 'student'
AUDIENCE_TEACHER = 'teacher'
AUDIENCES = (
    (AUDIENCE_ALL, '全体'),
    (AUDIENCE_STUDENT, '学生'),
    (AUDIENCE_TEACHER, '教师'),
)

ANNOUNCEMENT_DRAFT = 'draft'
ANNOUNCEMENT_PUBLISHED = 'published'
ANNOUNCEMENT_STATUS = (
    (ANNOUNCEMENT_DRAFT, '草稿'),
    (ANNOUNCEMENT_PUBLISHED, '已发布'),
)


class Announcement(models.Model):
    title = models.CharField('标题', max_length=120)
    body = models.TextField('正文', max_length=5000)
    audience = models.CharField('受众', max_length=16, choices=AUDIENCES,
                                default=AUDIENCE_ALL)
    status = models.CharField('状态', max_length=16, choices=ANNOUNCEMENT_STATUS,
                              default=ANNOUNCEMENT_DRAFT)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)

    class Meta:
        verbose_name = '公告'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['status', '-published_at'])]

    def __str__(self):
        return self.title
