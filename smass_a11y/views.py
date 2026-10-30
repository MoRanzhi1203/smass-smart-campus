"""S19 页面层：可访问性审计报告。"""
from __future__ import annotations

from functools import wraps
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from r21_account import authorization as authz
from r21_account.models import RoleCode

from . import services

ADMIN_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})


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


def can_view(user):
    roles = set(authz.active_roles(user))
    if roles & ADMIN_ROLES:
        return True
    return authz.has_action(user, 'manage_roles')


@require_GET
@require_login
def report(request):
    if not can_view(request.user):
        return render(request, 's19/forbidden.html',
                      {'message': '只有管理员可以查看可访问性报告'}, status=403)
    root = Path(settings.BASE_DIR) / 'templates'
    results = services.audit_dir(root)
    colors = [
        {'fg': fg, 'bg': bg, 'ratio': services.contrast_ratio(fg, bg),
         'level': services.wcag_level(services.contrast_ratio(fg, bg), large)}
        for fg, bg, large in services.COLOR_PAIRS
    ]
    return render(request, 's19/report.html', {
        'summary': services.summarize(results),
        'problems': [item for item in results if item['issues']],
        'colors': colors,
    })
