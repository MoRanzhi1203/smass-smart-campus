"""R15 页面层：群团组织、成员申请审批与干部任职。

权限原则
--------
- 所有页面要求登录；
- 创建组织只对教师/管理员开放；
- 社团负责人可审批本社团加入、任命/卸任本社团干部；
- 学生只能看到自己的成员记录与任职（管理员/负责人可见全量）。
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import (
    CLUB_CATEGORIES,
    Club,
    ClubMembership,
    ClubPost,
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
    return render(request, 'r15/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


# ---------------------------------------------------------------------------
# 组织
# ---------------------------------------------------------------------------
@require_GET
@require_login
def club_list(request):
    can_manage = services.can_manage(request.user)
    clubs = list(services.scoped_clubs(request.user,
                                       category=request.GET.get('category') or None))
    rows = [{'club': c, 'stats': services.club_stats(c)} for c in clubs]
    return render(request, 'r15/clubs.html', {
        'rows': rows,
        'can_manage': can_manage,
        'categories': CLUB_CATEGORIES,
        **_flash(request),
    })


@require_POST
@require_login
def club_create(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    try:
        services.create_club(
            request.user,
            request.POST.get('code', ''),
            request.POST.get('name', ''),
            (request.POST.get('category') or '').strip(),
            description=request.POST.get('description', ''),
        )
    except services.ClubError as exc:
        return redirect('/r15/clubs/?error={}'.format(quote(str(exc))))
    return redirect('/r15/clubs/?ok={}'.format(quote('组织已创建')))


@require_GET
@require_login
def club_detail(request, pk):
    club = get_object_or_404(Club.objects.select_related('parent', 'advisor'), pk=pk)
    can_manage = services.can_manage(request.user)
    can_admin = services.can_admin_club(request.user, club)
    if can_admin:
        # 负责人/管理员需要看到全部成员与任职才能审批与任命
        memberships = list(club.memberships.select_related('record').order_by(
            'status', 'record__student_no'))
        posts = list(club.posts.select_related('record').order_by('title', 'record__student_no'))
    else:
        memberships = list(services.scoped_memberships(request.user, club=club))
        posts = list(services.scoped_posts(request.user, club=club))
    my_membership = None
    my_record = services.record_for_account(request.user)
    if my_record is not None:
        my_membership = ClubMembership.objects.filter(
            club=club, record=my_record).first()
    return render(request, 'r15/club_detail.html', {
        'club': club,
        'can_manage': can_manage,
        'can_admin': can_admin,
        'memberships': memberships,
        'posts': posts,
        'my_membership': my_membership,
        'my_record': my_record,
        'stats': services.club_stats(club),
        **_flash(request),
    })


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------
@require_POST
@require_login
def club_apply(request, pk):
    club = get_object_or_404(Club, pk=pk)
    record = services.record_for_account(request.user)
    try:
        services.apply_join(club, record, request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ClubError as exc:
        return redirect('/r15/clubs/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r15/clubs/{}/?ok={}'.format(pk, quote('申请已提交')))


@require_POST
@require_login
def membership_action(request, pk, action):
    membership = get_object_or_404(
        ClubMembership.objects.select_related('club', 'record'), pk=pk)
    try:
        if action == 'approve':
            services.approve_join(membership, request.user)
        elif action == 'reject':
            services.reject_join(membership, request.user, request.POST.get('reason', ''))
        elif action == 'leave':
            services.leave_club(membership, request.user)
        elif action == 'promote':
            services.promote_leader(membership, request.user)
        elif action == 'demote':
            services.demote_leader(membership, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ClubError as exc:
        return redirect('/r15/clubs/{}/?error={}'.format(
            membership.club_id, quote(str(exc))))
    return redirect('/r15/clubs/{}/?ok={}'.format(
        membership.club_id, quote('操作成功')))


# ---------------------------------------------------------------------------
# 任职
# ---------------------------------------------------------------------------
@require_POST
@require_login
def post_appoint(request, pk):
    club = get_object_or_404(Club, pk=pk)
    from smass_organization.models import StudentRecord
    record = StudentRecord.objects.filter(
        pk=_parse_pk(request.POST.get('record'))).first()
    try:
        services.appoint_post(
            club, record, (request.POST.get('title') or '').strip(),
            request.POST.get('term', ''), request.user,
            note=request.POST.get('note', ''))
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ClubError as exc:
        return redirect('/r15/clubs/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r15/clubs/{}/?ok={}'.format(pk, quote('任命成功')))


@require_POST
@require_login
def post_end(request, pk):
    post = get_object_or_404(ClubPost.objects.select_related('club'), pk=pk)
    try:
        services.end_post(post, request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ClubError as exc:
        return redirect('/r15/clubs/{}/?error={}'.format(
            post.club_id, quote(str(exc))))
    return redirect('/r15/clubs/{}/?ok={}'.format(post.club_id, quote('已卸任')))


@require_GET
@require_login
def post_list(request):
    posts = list(services.scoped_posts(request.user))
    return render(request, 'r15/posts.html', {
        'posts': posts,
        'can_manage': services.can_manage(request.user),
        **_flash(request),
    })


def _parse_pk(raw):
    """把请求参数转成合法主键；非法值返回 None，避免 ValueError 变成 500。"""
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None
