"""R17 页面层：论坛板块、帖子、评论、举报处理与公告。

权限原则
--------
- 浏览：登录用户；未发布公告对学生不可见；
- 发帖/评论：登录用户；作者只能管理自己的内容（下架），删除仅版主/管理员；
- 举报：登录用户；处理仅版主/管理员；
- 公告创建与发布仅版主/管理员。
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import (
    AUDIENCES,
    TARGET_COMMENT,
    TARGET_POST,
    Announcement,
    Board,
    Post,
    Report,
)


def _login_url():
    return getattr(settings, 'LOGIN_URL', '/r21/login/')


def require_login(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_authenticated', False):
            target = request.get_full_path()
            return redirect('{}?next={}'.format(_login_url(), quote(target)))
        return view(request, *args, **kwargs)

    return _wrapped


def _forbidden(request, message='当前账号没有访问该页面的权限'):
    return render(request, 'r17/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def forum_index(request):
    can_moderate = services.can_moderate(request.user)
    boards = list(Board.objects.filter(status='active'))
    rows = [{'board': b, 'stats': services.board_stats(b)} for b in boards]
    posts = list(services.visible_posts(request.user)[:20])
    announcements = list(services.visible_announcements(request.user)[:10])
    return render(request, 'r17/forum.html', {
        'rows': rows,
        'posts': posts,
        'announcements': announcements,
        'can_moderate': can_moderate,
        **_flash(request),
    })


@require_GET
@require_login
def board_detail(request, pk):
    board = get_object_or_404(Board, pk=pk)
    posts = list(services.visible_posts(request.user, board=board)[:50])
    return render(request, 'r17/board.html', {
        'board': board,
        'posts': posts,
        'can_moderate': services.can_moderate(request.user),
        **_flash(request),
    })


@require_POST
@require_login
def post_create(request, pk):
    board = get_object_or_404(Board, pk=pk)
    try:
        post = services.create_post(
            board, request.user,
            request.POST.get('title', ''), request.POST.get('body', ''))
    except services.ForumError as exc:
        return redirect('/r17/forum/board/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r17/forum/post/{}/?ok={}'.format(post.pk, quote('帖子已发布')))


@require_GET
@require_login
def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related('board', 'author'), pk=pk)
    comments = list(services.visible_comments(request.user, post))
    is_author = str(post.author_id) == str(getattr(request.user, 'pk', ''))
    return render(request, 'r17/post.html', {
        'post': post,
        'comments': comments,
        'can_moderate': services.can_moderate(request.user),
        'is_author': is_author,
        **_flash(request),
    })


@require_POST
@require_login
def comment_create(request, pk):
    post = get_object_or_404(Post, pk=pk)
    try:
        services.create_comment(post, request.user, request.POST.get('body', ''))
    except services.ForumError as exc:
        return redirect('/r17/forum/post/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r17/forum/post/{}/?ok={}'.format(pk, quote('评论已发布')))


@require_POST
@require_login
def content_report(request):
    target_type = (request.POST.get('target_type') or '').strip()
    target_id = request.POST.get('target_id') or 0
    try:
        services.report_content(target_type, int(target_id), request.user,
                                request.POST.get('reason', ''))
    except (services.ForumError, ValueError) as exc:
        target = request.POST.get('next') or '/r17/forum/'
        return redirect('{}?error={}'.format(target, quote(str(exc))))
    target = request.POST.get('next') or '/r17/forum/'
    return redirect('{}?ok={}'.format(target, quote('举报已提交')))


@require_POST
@require_login
def content_action(request, pk):
    action = (request.POST.get('action') or '').strip()
    try:
        if action == 'hide':
            services.hide_content(TARGET_POST, pk, request.user)
        elif action == 'remove':
            services.remove_content(TARGET_POST, pk, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ForumError as exc:
        return redirect('/r17/forum/post/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r17/forum/post/{}/?ok={}'.format(pk, quote('内容已处理')))


@require_GET
@require_login
def report_list(request):
    if not services.can_moderate(request.user):
        return _forbidden(request)
    reports = list(services.scoped_reports(request.user))
    return render(request, 'r17/reports.html', {
        'reports': reports,
        **_flash(request),
    })


@require_POST
@require_login
def report_resolve(request, pk):
    report = get_object_or_404(Report, pk=pk)
    try:
        services.resolve_report(report, request.user,
                                (request.POST.get('action') or '').strip())
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ForumError as exc:
        return redirect('/r17/reports/?error={}'.format(quote(str(exc))))
    return redirect('/r17/reports/?ok={}'.format(quote('举报已处理')))


@require_GET
@require_login
def announcement_list(request):
    can_moderate = services.can_moderate(request.user)
    announcements = list(services.visible_announcements(request.user))
    return render(request, 'r17/announcements.html', {
        'announcements': announcements,
        'can_moderate': can_moderate,
        'audiences': AUDIENCES,
        **_flash(request),
    })


@require_POST
@require_login
def announcement_create(request):
    if not services.can_moderate(request.user):
        return _forbidden(request)
    try:
        services.create_announcement(
            request.user, request.POST.get('title', ''),
            request.POST.get('body', ''),
            (request.POST.get('audience') or 'all').strip())
    except services.ForumError as exc:
        return redirect('/r17/announcements/?error={}'.format(quote(str(exc))))
    return redirect('/r17/announcements/?ok={}'.format(quote('公告已创建（草稿）')))


@require_POST
@require_login
def announcement_publish(request, pk):
    if not services.can_moderate(request.user):
        return _forbidden(request)
    announcement = get_object_or_404(Announcement, pk=pk)
    try:
        services.publish_announcement(announcement, request.user)
    except services.ForumError as exc:
        return redirect('/r17/announcements/?error={}'.format(quote(str(exc))))
    return redirect('/r17/announcements/?ok={}'.format(quote('公告已发布')))
