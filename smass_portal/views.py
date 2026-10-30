"""R20 页面层：多角色统一门户与配置后台。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import ALL_ROLES, PortalNotice, PortalSection


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
    return render(request, 'r20/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def portal_home(request):
    context = services.portal_context(request.user)
    return render(request, 'r20/home.html', {
        'sections': context['sections'],
        'notices': context['notices'],
        'roles': context['roles'],
        'can_admin': services.can_admin_portal(request.user),
        **_flash(request),
    })


@require_GET
@require_login
def portal_admin(request):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    sections = []
    for section in PortalSection.objects.all():
        sections.append({
            'section': section,
            'links': list(section.links.order_by('sort_order', 'id')),
        })
    return render(request, 'r20/admin.html', {
        'sections': sections,
        'notices': list(PortalNotice.objects.order_by('-created_at')[:50]),
        'stats': services.section_stats(),
        'all_roles': ALL_ROLES,
        **_flash(request),
    })


@require_POST
@require_login
def admin_bootstrap(request):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    result = services.bootstrap_defaults()
    return redirect('/r20/admin/?ok={}'.format(quote(
        '默认门户已初始化（新区块 {} / 新链接 {}）'.format(
            result['sections'], result['links']))))


@require_POST
@require_login
def section_create(request):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    try:
        services.create_section(
            request.user, request.POST.get('code', ''), request.POST.get('title', ''),
            roles=request.POST.get('roles') or ALL_ROLES,
            subtitle=request.POST.get('subtitle', ''),
            sort_order=request.POST.get('sort_order') or 0)
    except services.PortalError as exc:
        return redirect('/r20/admin/?error={}'.format(quote(str(exc))))
    return redirect('/r20/admin/?ok={}'.format(quote('区块已创建')))


@require_POST
@require_login
def link_create(request):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    section = get_object_or_404(PortalSection, pk=request.POST.get('section') or 0)
    try:
        services.create_link(
            section, request.POST.get('label', ''),
            url_name=request.POST.get('url_name', ''),
            fallback_url=request.POST.get('fallback_url', ''),
            roles=request.POST.get('roles') or ALL_ROLES,
            actor=request.user,
            sort_order=request.POST.get('sort_order') or 0)
    except services.PortalError as exc:
        return redirect('/r20/admin/?error={}'.format(quote(str(exc))))
    return redirect('/r20/admin/?ok={}'.format(quote('链接已创建')))


@require_POST
@require_login
def notice_create(request):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    try:
        services.create_notice(
            request.user, request.POST.get('title', ''),
            request.POST.get('body', ''),
            roles=request.POST.get('roles') or ALL_ROLES)
    except services.PortalError as exc:
        return redirect('/r20/admin/?error={}'.format(quote(str(exc))))
    return redirect('/r20/admin/?ok={}'.format(quote('公告已创建（草稿）')))


@require_POST
@require_login
def notice_publish(request, pk):
    if not services.can_admin_portal(request.user):
        return _forbidden(request)
    notice = get_object_or_404(PortalNotice, pk=pk)
    try:
        services.publish_notice(notice, request.user)
    except services.PortalError as exc:
        return redirect('/r20/admin/?error={}'.format(quote(str(exc))))
    return redirect('/r20/admin/?ok={}'.format(quote('公告已发布')))
