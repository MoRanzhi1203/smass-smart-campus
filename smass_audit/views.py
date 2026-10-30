"""S16 页面层：审计事件、链校验与安全告警。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import SecurityAlert


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
    return render(request, 's16/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def event_list(request):
    events = list(services.scoped_events(request.user)[:200])
    return render(request, 's16/events.html', {
        'events': events,
        'stats': services.stats(request.user),
        'can_audit': services.can_audit(request.user),
        **_flash(request),
    })


@require_GET
@require_login
def alert_list(request):
    if not services.can_audit(request.user):
        return _forbidden(request)
    alerts = list(services.scoped_alerts(request.user)[:100])
    return render(request, 's16/alerts.html', {
        'alerts': alerts,
        **_flash(request),
    })


@require_POST
@require_login
def alert_scan(request):
    if not services.can_audit(request.user):
        return _forbidden(request)
    created = services.detect_alerts()
    return redirect('/s16/alerts/?ok={}'.format(quote(
        '扫描完成，新增告警 {} 条'.format(created))))


@require_POST
@require_login
def alert_ack(request, pk):
    alert = get_object_or_404(SecurityAlert, pk=pk)
    try:
        services.acknowledge_alert(alert, request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.AuditError as exc:
        return redirect('/s16/alerts/?error={}'.format(quote(str(exc))))
    return redirect('/s16/alerts/?ok={}'.format(quote('告警已确认')))
