"""三端共用：个人中心、通知中心、无角色提示。"""
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import permissions as perms


def _kind_of(request):
    account = getattr(request, 'user', None)
    return perms.landing_kind(account)


def no_role(request):
    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect(perms.landing_url(account) if account else '/login/')
    return render(request, 'workspace/no_role.html', {
        'workspace_kind': None,
        'account': account,
        'roles': [perms.ROLE_LABEL.get(r, r) for r in sorted(perms.active_roles(account))],
    }, status=403)


def profile(request):
    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect('/login/?next=/profile/')

    from smass_organization.models import OrganizationMembership, StudentRecord

    record = StudentRecord.objects.filter(account=account).first()
    memberships = list(
        OrganizationMembership.objects.filter(
            account=account, ended_at__isnull=True)
        .select_related('unit').order_by('unit__sort_order'))

    return render(request, 'workspace/profile.html', {
        'workspace_kind': _kind_of(request),
        'account': account,
        'record': record,
        'memberships': memberships,
        'roles': [perms.ROLE_LABEL.get(r, r) for r in sorted(perms.active_roles(account))],
        'kinds': [perms.KIND_LABEL[k] for k in
                  (perms.KIND_ADMIN, perms.KIND_TEACHER, perms.KIND_STUDENT)
                  if k in perms.allowed_kinds(account)],
    })


def notifications(request):
    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect('/login/?next=/notifications/')

    from smass_forum.models import Announcement
    from smass_workflow.models import Notification

    kind = _kind_of(request)
    role_code = {
        perms.KIND_ADMIN: 'admin',
        perms.KIND_TEACHER: 'teacher',
        perms.KIND_STUDENT: 'student',
    }.get(kind, 'student')

    items = []
    # 1) 站内通知（工作流引擎产生，定向到人；账号外键优先，兼容旧字符串）
    from django.db.models import Q

    note_query = (Q(recipient_account=account)
                  | Q(recipient=account.login_name))
    for note in Notification.objects.filter(note_query).order_by('-created_at')[:80]:
        items.append({
            'id': note.pk,
            'title': note.title,
            'body': note.body,
            'time': note.created_at,
            'level': note.level,
            'is_read': note.is_read,
            'source': '站内通知',
        })

    # 2) 全校公告（按受众过滤）
    for note in Announcement.objects.filter(
            status='published').order_by('-published_at', '-created_at')[:60]:
        if note.audience not in ('all', role_code):
            continue
        items.append({
            'id': None,
            'title': note.title,
            'body': note.body,
            'time': note.published_at or note.created_at,
            'level': 'info',
            'is_read': True,
            'source': '校园公告',
        })

    items.sort(key=lambda item: item['time'] or timezone.now(), reverse=True)

    unread_count = Notification.objects.filter(
        note_query, is_read=False).count()

    return render(request, 'workspace/notifications.html', {
        'workspace_kind': kind,
        'items': items,
        'total': len(items),
        'unread_count': unread_count,
    })


@require_POST
def notification_read(request, pk):
    from smass_workflow.models import Notification

    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect('/login/?next=/notifications/')
    from django.db.models import Q

    note = Notification.objects.filter(
        pk=pk).filter(
        Q(recipient_account=account) | Q(recipient=account.login_name)).first()
    if note is not None and not note.is_read:
        note.is_read = True
        note.save(update_fields=['is_read'])
    return redirect('workspace:notifications')


@require_POST
def notifications_read_all(request):
    from smass_workflow.models import Notification

    account = getattr(request, 'user', None)
    if not perms.is_authenticated(account):
        return redirect('/login/?next=/notifications/')
    from django.db.models import Q

    Notification.objects.filter(
        Q(recipient_account=account) | Q(recipient=account.login_name),
        is_read=False).update(is_read=True)
    return redirect('workspace:notifications')


def forbid(request, detail=''):
    """统一的 403 渲染（供其它视图复用）。"""
    account = getattr(request, 'user', None)
    return render(request, 'workspace/403.html', {
        'workspace_kind': getattr(request, 'workspace_kind', None),
        'attempted_label': '该功能',
        'roles': [perms.ROLE_LABEL.get(r, r)
                  for r in sorted(perms.active_roles(account))],
        'landing_url': perms.landing_url(account),
        'detail': detail,
    }, status=403)


def toast(request, text, level='success'):
    getattr(messages, level)(request, text)
