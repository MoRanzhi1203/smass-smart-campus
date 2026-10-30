"""S15 视图：示例 API 端点与管理页面。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from smass_organization.models import StudentRecord

from . import services
from .decorators import api_endpoint
from .models import ApiToken


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------
@api_endpoint(scope=None, limit=10)
@require_http_methods(['GET'])
def ping(request, token):
    return {'status': True, 'client': token.client.client_id,
            'scopes': [s for s in (token.scopes or '').split(',') if s]}


@api_endpoint(scope='students:read', limit=5, idempotent=True)
@require_POST
def students_count(request, token):
    body = request.body.decode('utf-8', 'replace') if request.body else ''
    return {'status': True, 'count': StudentRecord.objects.count(),
            'echo_bytes': len(body)}


# ---------------------------------------------------------------------------
# 管理页面
# ---------------------------------------------------------------------------
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
    return render(request, 's15/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
        'issued_token': request.session.pop('s15_issued_token', ''),
    }


def _parse_pk(raw):
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None


@require_GET
@require_login
def admin(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    from django.utils import timezone
    return render(request, 's15/admin.html', {
        'clients': list(services.client_rows()),
        'tokens': list(services.token_rows()[:50]),
        'logs': list(services.scoped_logs(request.user)[:30]),
        'now': timezone.now(),
        **_flash(request),
    })


@require_POST
@require_login
def client_create(request):
    try:
        services.create_client(request.user, request.POST.get('name', ''))
    except services.ApiError as exc:
        return redirect('/s15/?error={}'.format(quote(str(exc))))
    return redirect('/s15/?ok={}'.format(quote('客户端已创建')))


@require_POST
@require_login
def token_create(request):
    client = services.ApiClient.objects.filter(
        pk=_parse_pk(request.POST.get('client'))).first()
    if client is None:
        return redirect('/s15/?error={}'.format(quote('客户端不存在')))
    scopes = [item.strip() for item in (request.POST.get('scopes') or '').split(',')
              if item.strip()]
    try:
        ttl = int(request.POST.get('ttl') or 3600)
    except ValueError:
        ttl = 3600
    try:
        raw, _token = services.issue_token(client, scopes, ttl_seconds=ttl)
    except services.ApiError as exc:
        return redirect('/s15/?error={}'.format(quote(str(exc))))
    request.session['s15_issued_token'] = raw
    return redirect('/s15/?ok={}'.format(quote('令牌已签发（仅显示一次）')))


@require_POST
@require_login
def token_revoke(request, pk):
    token = get_object_or_404(ApiToken, pk=pk)
    try:
        services.revoke_token(token, request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.ApiError as exc:
        return redirect('/s15/?error={}'.format(quote(str(exc))))
    return redirect('/s15/?ok={}'.format(quote('令牌已吊销')))
