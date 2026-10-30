"""S11 页面层：字段策略配置与预览。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from smass_organization.models import StudentRecord

from . import services
from .models import MASK_CHOICES, FieldPolicy

DEMO_RESOURCE = 'student_record'


def _parse_pk(raw):
    """把请求参数转成合法主键；非法值返回 None，避免 ValueError 变成 500。"""
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None


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
    return render(request, 's11/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def policy_list(request):
    can_admin = services.can_admin(request.user)
    if not can_admin:
        return _forbidden(request)
    return render(request, 's11/policies.html', {
        'policies': list(services.scoped_policies(request.user)),
        'masks': MASK_CHOICES,
        'logs': list(services.decision_logs(request.user)[:20]),
        **_flash(request),
    })


@require_POST
@require_login
def policy_save(request):
    if not services.can_admin(request.user):
        return _forbidden(request)
    condition = {}
    status = (request.POST.get('condition_status') or '').strip()
    if status:
        condition['status'] = [item.strip() for item in status.split(',') if item.strip()]
    try:
        services.set_policy(
            request.user,
            request.POST.get('resource', DEMO_RESOURCE),
            request.POST.get('field', ''),
            read_roles=request.POST.get('read_roles', ''),
            write_roles=request.POST.get('write_roles', ''),
            mask=(request.POST.get('mask') or 'none').strip(),
            condition=condition,
            note=request.POST.get('note', ''),
            enabled=bool(request.POST.get('enabled', 'on')),
        )
    except services.PolicyError as exc:
        return redirect('/s11/policies/?error={}'.format(quote(str(exc))))
    return redirect('/s11/policies/?ok={}'.format(quote('策略已保存')))


@require_POST
@require_login
def policy_disable(request, pk):
    policy = get_object_or_404(FieldPolicy, pk=pk)
    try:
        services.disable_policy(request.user, policy)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.PolicyError as exc:
        return redirect('/s11/policies/?error={}'.format(quote(str(exc))))
    return redirect('/s11/policies/?ok={}'.format(quote('策略已停用')))


@require_GET
@require_login
def preview(request):
    """用当前登录账号试读字段策略（含脱敏效果）。"""
    record = StudentRecord.objects.filter(
        pk=_parse_pk(request.GET.get('record'))).first()
    if record is None:
        record = StudentRecord.objects.order_by('student_no').first()
    fields = services.effective_fields(
        request.user, DEMO_RESOURCE, obj=record)
    rows = []
    for field, info in fields.items():
        row = {'field': field, 'info': info, 'value': None, 'masked': False}
        if info['read']:
            result = services.read_field(
                request.user, DEMO_RESOURCE, field, obj=record)
            row['value'] = result['value']
            row['masked'] = result['masked']
        rows.append(row)
    return render(request, 's11/preview.html', {
        'record': record,
        'rows': rows,
        'can_admin': services.can_admin(request.user),
        **_flash(request),
    })
