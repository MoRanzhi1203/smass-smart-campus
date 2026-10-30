"""R17 服务层：论坛发帖、评论、举报处理与公告。

规则摘要
--------
- 发帖/评论：登录账号、板块正常、标题/正文非空；内容默认 ``published``；
- 内容处置：作者本人可下架自己的内容；版主/管理员可下架或删除任意内容；
  ``removed`` 为终态，不做物理删除（保留审计）；
- 举报：同一人对同一对象只能有一条待处理举报；处理时必须给出动作，
  处理结果与内容状态同时落库；
- 公告：管理员创建（草稿）→ 发布；未发布公告对学生不可见。
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    ANNOUNCEMENT_DRAFT,
    ANNOUNCEMENT_PUBLISHED,
    AUDIENCES,
    BOARD_ACTIVE,
    CONTENT_HIDDEN,
    CONTENT_PUBLISHED,
    CONTENT_REMOVED,
    REPORT_ACTION_DISMISS,
    REPORT_ACTION_HIDE,
    REPORT_ACTION_REMOVE,
    REPORT_ACTIONS,
    REPORT_DISMISSED,
    REPORT_PENDING,
    REPORT_RESOLVED,
    TARGET_COMMENT,
    TARGET_POST,
    TARGET_TYPES,
    Announcement,
    Board,
    Comment,
    Post,
    Report,
)

logger = logging.getLogger('smass.audit')

MODERATOR_ROLES = frozenset({
    RoleCode.TEACHER, RoleCode.COLLEGE_ADMIN, RoleCode.SYSTEM_ADMIN,
})


class ForumError(ValueError):
    def __init__(self, message, code='FORUM_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(ForumError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def can_moderate(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & MODERATOR_ROLES:
        return True
    return authz.has_action(account, 'update')


def _require_moderator(account):
    if not can_moderate(account):
        raise PermissionDenied('只有版主或管理员可以执行该操作')


# ---------------------------------------------------------------------------
# 板块与内容
# ---------------------------------------------------------------------------
def create_board(actor, code, name, description=''):
    _require_moderator(actor)
    if not str(code or '').strip() or not str(name or '').strip():
        raise ForumError('板块编码与名称不能为空', code='EMPTY_FIELD')
    if Board.objects.filter(code=str(code).strip()).exists():
        raise ForumError('板块编码已存在', code='DUPLICATE_CODE')
    board = Board.objects.create(
        code=str(code).strip()[:64], name=str(name).strip()[:64],
        description=str(description or '')[:200], status=BOARD_ACTIVE)
    logger.info('forum_board_created id=%s code=%s by=%s',
                board.pk, board.code, _actor_id(actor))
    return board


def create_post(board, author, title, body):
    if getattr(author, 'pk', None) is None:
        raise ForumError('请先登录', code='NOT_AUTHENTICATED')
    if board is None or board.status != BOARD_ACTIVE:
        raise ForumError('板块不存在或已归档', code='BOARD_UNAVAILABLE')
    if not str(title or '').strip():
        raise ForumError('标题不能为空', code='EMPTY_TITLE')
    if not str(body or '').strip():
        raise ForumError('正文不能为空', code='EMPTY_BODY')

    post = Post.objects.create(
        board=board, author=author,
        title=str(title).strip()[:120],
        body=str(body).strip()[:5000],
        status=CONTENT_PUBLISHED)
    logger.info('forum_post_created id=%s board=%s by=%s',
                post.pk, board.code, _actor_id(author))
    return post


def create_comment(post, author, body):
    if getattr(author, 'pk', None) is None:
        raise ForumError('请先登录', code='NOT_AUTHENTICATED')
    if post is None or post.status != CONTENT_PUBLISHED:
        raise ForumError('帖子不可评论', code='POST_UNAVAILABLE')
    if not str(body or '').strip():
        raise ForumError('评论内容不能为空', code='EMPTY_BODY')
    comment = Comment.objects.create(
        post=post, author=author, body=str(body).strip()[:2000],
        status=CONTENT_PUBLISHED)
    logger.info('forum_comment_created id=%s post=%s by=%s',
                comment.pk, post.pk, _actor_id(author))
    return comment


def _target_object(target_type, target_id):
    if target_type == TARGET_POST:
        return Post.objects.filter(pk=target_id).first()
    if target_type == TARGET_COMMENT:
        return Comment.objects.filter(pk=target_id).first()
    raise ForumError('未知的内容类型', code='BAD_TARGET')


def _set_status(obj, status, actor, reason=''):
    if obj.status == CONTENT_REMOVED:
        raise ForumError('内容已删除，不能再次处理', code='TERMINAL_STATE')
    obj.status = status
    obj.save(update_fields=['status'] + (['updated_at'] if hasattr(obj, 'updated_at') else []))
    logger.info('forum_content_%s type=%s id=%s by=%s',
                status, type(obj).__name__, obj.pk, _actor_id(actor))


def hide_content(target_type, target_id, actor, reason=''):
    obj = _target_object(target_type, target_id)
    if obj is None:
        raise ForumError('内容不存在', code='NOT_FOUND')
    is_author = str(getattr(obj.author, 'pk', '')) == _actor_id(actor)
    if not is_author and not can_moderate(actor):
        raise PermissionDenied('只能管理自己的内容')
    _set_status(obj, CONTENT_HIDDEN, actor, reason)
    return obj


def remove_content(target_type, target_id, actor, reason=''):
    _require_moderator(actor)
    obj = _target_object(target_type, target_id)
    if obj is None:
        raise ForumError('内容不存在', code='NOT_FOUND')
    _set_status(obj, CONTENT_REMOVED, actor, reason)
    return obj


# ---------------------------------------------------------------------------
# 举报
# ---------------------------------------------------------------------------
def report_content(target_type, target_id, reporter, reason):
    if getattr(reporter, 'pk', None) is None:
        raise ForumError('请先登录', code='NOT_AUTHENTICATED')
    if target_type not in dict(TARGET_TYPES):
        raise ForumError('未知的内容类型', code='BAD_TARGET')
    if not str(reason or '').strip():
        raise ForumError('举报必须填写理由', code='EMPTY_REASON')
    obj = _target_object(target_type, target_id)
    if obj is None or obj.status == CONTENT_REMOVED:
        raise ForumError('内容不存在或已删除', code='NOT_FOUND')

    if Report.objects.filter(
            target_type=target_type, target_id=target_id,
            reporter=reporter, status=REPORT_PENDING).exists():
        raise ForumError('你已举报过该内容，请等待处理', code='DUPLICATE_REPORT')

    report = Report.objects.create(
        target_type=target_type, target_id=target_id, reporter=reporter,
        reason=str(reason).strip()[:500], status=REPORT_PENDING)
    logger.info('forum_report_created id=%s type=%s target=%s by=%s',
                report.pk, target_type, target_id, _actor_id(reporter))
    return report


def resolve_report(report, actor, action):
    _require_moderator(actor)
    if action not in dict(REPORT_ACTIONS):
        raise ForumError('未知的处理动作', code='BAD_ACTION')
    if report.status != REPORT_PENDING:
        raise ForumError('该举报已处理', code='BAD_STATE')

    with transaction.atomic():
        locked = Report.objects.select_for_update().get(pk=report.pk)
        if locked.status != REPORT_PENDING:
            raise ForumError('该举报已处理', code='BAD_STATE')

        if action == REPORT_ACTION_HIDE:
            _set_status(_target_object(locked.target_type, locked.target_id),
                        CONTENT_HIDDEN, actor, '举报处理')
            locked.status = REPORT_RESOLVED
        elif action == REPORT_ACTION_REMOVE:
            _set_status(_target_object(locked.target_type, locked.target_id),
                        CONTENT_REMOVED, actor, '举报处理')
            locked.status = REPORT_RESOLVED
        else:
            locked.status = REPORT_DISMISSED

        locked.action = action
        locked.handled_by = _actor_id(actor)
        locked.handled_at = timezone.now()
        locked.save(update_fields=['status', 'action', 'handled_by', 'handled_at'])

    logger.info('forum_report_resolved id=%s action=%s by=%s',
                report.pk, action, _actor_id(actor))
    return locked


# ---------------------------------------------------------------------------
# 公告
# ---------------------------------------------------------------------------
def create_announcement(actor, title, body, audience='all'):
    _require_moderator(actor)
    if not str(title or '').strip() or not str(body or '').strip():
        raise ForumError('公告标题与正文不能为空', code='EMPTY_FIELD')
    if audience not in dict(AUDIENCES):
        raise ForumError('未知受众', code='BAD_AUDIENCE')
    announcement = Announcement.objects.create(
        title=str(title).strip()[:120], body=str(body).strip()[:5000],
        audience=audience, status=ANNOUNCEMENT_DRAFT,
        created_by=_actor_id(actor))
    logger.info('announcement_created id=%s by=%s',
                announcement.pk, _actor_id(actor))
    return announcement


def publish_announcement(announcement, actor):
    _require_moderator(actor)
    if announcement.status != ANNOUNCEMENT_DRAFT:
        raise ForumError('只有草稿公告可以发布', code='BAD_STATE')
    announcement.status = ANNOUNCEMENT_PUBLISHED
    announcement.published_at = timezone.now()
    announcement.save(update_fields=['status', 'published_at'])
    logger.info('announcement_published id=%s by=%s',
                announcement.pk, _actor_id(actor))
    return announcement


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def visible_posts(account, board=None):
    qs = Post.objects.select_related('board', 'author')
    if board is not None:
        qs = qs.filter(board=board)
    if can_moderate(account):
        return qs.order_by('-pinned', '-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.filter(status=CONTENT_PUBLISHED).order_by('-pinned', '-created_at')
    return qs.filter(
        models_q_visible(account)
    ).order_by('-pinned', '-created_at')


def models_q_visible(account):
    from django.db.models import Q
    return Q(status=CONTENT_PUBLISHED) | Q(author=account, status=CONTENT_HIDDEN)


def visible_comments(account, post):
    qs = Comment.objects.select_related('author').filter(post=post)
    if can_moderate(account):
        return qs.order_by('created_at')
    if getattr(account, 'pk', None) is None:
        return qs.filter(status=CONTENT_PUBLISHED).order_by('created_at')
    return qs.filter(models_q_visible(account)).order_by('created_at')


def scoped_reports(account):
    qs = Report.objects.select_related('reporter')
    if can_moderate(account):
        return qs.order_by('status', '-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(reporter=account).order_by('-created_at')


def visible_announcements(account):
    qs = Announcement.objects.all()
    if can_moderate(account):
        return qs.order_by('-published_at', '-created_at')
    roles = authz.active_roles(account)
    if RoleCode.TEACHER in roles:
        audiences = ['all', 'teacher']
    else:
        audiences = ['all', 'student']
    return qs.filter(status=ANNOUNCEMENT_PUBLISHED, audience__in=audiences).order_by(
        '-published_at')


def board_stats(board):
    return {
        'posts': board.posts.filter(status=CONTENT_PUBLISHED).count(),
        'comments': Comment.objects.filter(
            post__board=board, status=CONTENT_PUBLISHED).count(),
    }
