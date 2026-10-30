"""模板上下文：三端 shell 需要的导航、角色、未读数。"""
from __future__ import annotations

from . import navigation
from . import permissions as perms


def _infer_kind(path: str) -> str | None:
    if path.startswith('/student'):
        return perms.KIND_STUDENT
    if path.startswith('/teacher'):
        return perms.KIND_TEACHER
    if path.startswith('/admin'):
        return perms.KIND_ADMIN
    return None


def unread_notice_count(account) -> int:
    if not perms.is_authenticated(account):
        return 0
    try:
        from smass_workflow.models import Notification

        return Notification.objects.filter(
            recipient=account.login_name, is_read=False).count()
    except Exception:  # noqa: BLE001 - 迁移前或表缺失时按 0 处理
        return 0


def workspace(request):
    account = getattr(request, 'user', None)
    authenticated = perms.is_authenticated(account)
    kind = getattr(request, 'workspace_kind', None)
    if kind is None:
        kind = _infer_kind(request.path)

    roles = sorted(perms.active_roles(account)) if authenticated else []
    sections = navigation.sections_for(kind, account) if kind and authenticated else ()

    available = []
    if authenticated:
        for candidate in (perms.KIND_ADMIN, perms.KIND_TEACHER, perms.KIND_STUDENT):
            if candidate in perms.allowed_kinds(account):
                available.append({
                    'kind': candidate,
                    'label': perms.KIND_LABEL[candidate],
                    'url': '/{}/'.format(candidate),
                })

    return {
        'workspace_kind': kind,
        'workspace_label': perms.KIND_LABEL.get(kind, ''),
        'nav_sections': sections,
        'current_url_name': getattr(request, 'resolver_match', None)
        and request.resolver_match.view_name or '',
        'unread_notice_count': unread_notice_count(account) if authenticated else 0,
        'account_roles': [perms.ROLE_LABEL.get(item, item) for item in roles],
        'available_workspaces': available,
        'is_counselor': authenticated and perms.is_counselor(account),
        'is_system_admin': authenticated and perms.is_system_admin(account),
    }
