"""S13 页面层：字段分级、披露申请与脱敏导出。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import CLASSIFICATIONS, MASK_CHOICES, DataField, DisclosureRequest

RESOURCE = services.RESOURCE_STUDENT


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
    return render(request, 's13/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def field_list(request):
    if not services.can_manage(request.user):
        return _forbidden(request, '只有数据管理员可以查看字段分级')
    return render(request, 's13/fields.html', {
        'fields': list(DataField.objects.order_by('resource', 'field')),
        'classifications': CLASSIFICATIONS,
        'masks': MASK_CHOICES,
        'can_manage': True,
        'stats': services.stats(),
        'resource': RESOURCE,
        **_flash(request),
    })


@require_POST
@require_login
def field_save(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    try:
        services.set_field(
            request.user,
            request.POST.get('resource', RESOURCE),
            request.POST.get('field', ''),
            (request.POST.get('classification') or 'internal').strip(),
            mask=(request.POST.get('mask') or 'none').strip(),
            retention_days=request.POST.get('retention_days') or 0,
            note=request.POST.get('note', ''))
    except services.PrivacyError as exc:
        return redirect('/s13/fields/?error={}'.format(quote(str(exc))))
    return redirect('/s13/fields/?ok={}'.format(quote('字段分级已保存')))


@require_POST
@require_login
def field_purge(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    deleted = services.purge_expired()
    return redirect('/s13/fields/?ok={}'.format(
        quote('已清理过期样本 {} 条'.format(deleted))))


@require_GET
@require_login
def disclosure_list(request):
    can_manage = services.can_manage(request.user)
    services.expire_stale()
    return render(request, 's13/disclosures.html', {
        'requests': list(services.scoped_requests(request.user)[:100]),
        'fields': [item for item in services.fields_of(RESOURCE)],
        'can_manage': can_manage,
        'logs': list(services.scoped_logs(request.user)[:20]),
        'resource': RESOURCE,
        **_flash(request),
    })


@require_POST
@require_login
def disclosure_request(request):
    selected = request.POST.getlist('fields')
    try:
        services.request_disclosure(
            request.user, RESOURCE, selected,
            request.POST.get('purpose', ''))
    except services.PrivacyError as exc:
        return redirect('/s13/disclosures/?error={}'.format(quote(str(exc))))
    return redirect('/s13/disclosures/?ok={}'.format(quote('披露申请已提交')))


@require_POST
@require_login
def disclosure_action(request, pk, action):
    row = get_object_or_404(DisclosureRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_disclosure(row, request.user)
        elif action == 'reject':
            services.reject_disclosure(row, request.user,
                                       request.POST.get('reason', ''))
        elif action == 'execute':
            services.execute_disclosure(row, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.PrivacyError as exc:
        return redirect('/s13/disclosures/?error={}'.format(quote(str(exc))))
    return redirect('/s13/disclosures/?ok={}'.format(quote('操作成功')))


@require_GET
@require_login
def disclosure_export(request, pk):
    row = get_object_or_404(DisclosureRequest, pk=pk)
    if row.status != 'executed':
        return _forbidden(request, '只有已执行的披露可以下载')
    if not (services.can_manage(request.user)
            or str(row.requester_id) == str(getattr(request.user, 'pk', ''))):
        return _forbidden(request, '只能下载自己申请的数据')
    text, _rows, _digest = services.build_export(row)
    response = HttpResponse(text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="disclosure-{}.csv"'.format(
        row.pk)
    response['X-Content-Type-Options'] = 'nosniff'
    return response
