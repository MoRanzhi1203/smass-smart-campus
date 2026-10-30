"""R19 页面层：党建/专项组织、成员、活动与受控资料访问。

权限原则
--------
- 组织/成员/活动/资料的创建与维护只对党务管理员开放；
- 资料列表只展示元数据；正文必须经 ``view_document`` 判定，未授权返回脱敏占位；
- 每次查看（含被拒绝）都写访问审计；
- 借阅审批禁止自批。
"""
from __future__ import annotations

from datetime import datetime
from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from smass_organization.models import StudentRecord

from . import services
from .models import (
    ACTIVITY_TYPES,
    CLASSIFICATIONS,
    ORG_TYPES,
    POLITICAL_STATUS,
    AccessGrant,
    AccessRequest,
    PartyDocument,
    PartyOrg,
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
    return render(request, 'r19/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


@require_GET
@require_login
def org_list(request):
    can_manage = services.can_manage_party(request.user)
    orgs = list(services.scoped_orgs(request.user))
    rows = [{'org': o, 'stats': services.org_summary(o)} for o in orgs]
    return render(request, 'r19/orgs.html', {
        'rows': rows,
        'can_manage': can_manage,
        'org_types': ORG_TYPES,
        **_flash(request),
    })


@require_POST
@require_login
def org_create(request):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    try:
        services.create_org(
            request.user, request.POST.get('code', ''), request.POST.get('name', ''),
            (request.POST.get('org_type') or '').strip())
    except services.PartyError as exc:
        return redirect('/r19/orgs/?error={}'.format(quote(str(exc))))
    return redirect('/r19/orgs/?ok={}'.format(quote('组织已创建')))


@require_GET
@require_login
def org_detail(request, pk):
    org = get_object_or_404(PartyOrg.objects.select_related('parent'), pk=pk)
    can_manage = services.can_manage_party(request.user)
    is_member = services.is_org_member(request.user, org)
    if not can_manage and not is_member:
        return _forbidden(request, '只有本组织成员或党务管理员可以查看')
    members = list(org.members.select_related('record').order_by('record__student_no')) \
        if can_manage else []
    activities = list(org.activities.order_by('-held_on'))
    documents = list(services.scoped_documents(request.user, org=org))
    return render(request, 'r19/org_detail.html', {
        'org': org,
        'can_manage': can_manage,
        'is_member': is_member,
        'members': members,
        'activities': activities,
        'documents': documents,
        'stats': services.org_summary(org),
        'political_statuses': POLITICAL_STATUS,
        'activity_types': ACTIVITY_TYPES,
        'classifications': CLASSIFICATIONS,
        'records': list(StudentRecord.objects.order_by('student_no')[:200]) if can_manage else [],
        **_flash(request),
    })


@require_POST
@require_login
def member_add(request, pk):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    org = get_object_or_404(PartyOrg, pk=pk)
    record = StudentRecord.objects.filter(
        pk=_parse_pk(request.POST.get('record'))).first()
    try:
        services.add_member(
            org, record, (request.POST.get('political_status') or '').strip(),
            request.user, note=request.POST.get('note', ''))
    except services.PartyError as exc:
        return redirect('/r19/orgs/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r19/orgs/{}/?ok={}'.format(pk, quote('成员已添加')))


@require_POST
@require_login
def activity_create(request, pk):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    org = get_object_or_404(PartyOrg, pk=pk)
    try:
        services.create_activity(
            org, request.POST.get('title', ''),
            (request.POST.get('activity_type') or '').strip(),
            _parse_date(request.POST.get('held_on')), request.user,
            summary=request.POST.get('summary', ''))
    except services.PartyError as exc:
        return redirect('/r19/orgs/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r19/orgs/{}/?ok={}'.format(pk, quote('活动已创建')))


@require_POST
@require_login
def activity_complete(request, pk):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    from smass_party.models import PartyActivity
    activity = get_object_or_404(PartyActivity, pk=pk)
    try:
        services.complete_activity(activity, request.user,
                                   summary=request.POST.get('summary', ''))
    except services.PartyError as exc:
        return redirect('/r19/orgs/{}/?error={}'.format(
            activity.org_id, quote(str(exc))))
    return redirect('/r19/orgs/{}/?ok={}'.format(activity.org_id, quote('活动已完成')))


@require_POST
@require_login
def document_create(request, pk):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    org = get_object_or_404(PartyOrg, pk=pk)
    try:
        services.create_document(
            org, request.POST.get('title', ''),
            (request.POST.get('classification') or '').strip(),
            request.POST.get('summary', ''), request.user)
    except services.PartyError as exc:
        return redirect('/r19/orgs/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r19/orgs/{}/?ok={}'.format(pk, quote('资料已归档')))


@require_GET
@require_login
def document_detail(request, pk):
    document = get_object_or_404(
        PartyDocument.objects.select_related('org'), pk=pk)
    result = services.view_document(
        document, request.user, purpose='页面查看',
        ip=request.META.get('REMOTE_ADDR', ''))
    return render(request, 'r19/document.html', {
        'document': document,
        'result': result,
        'can_manage': services.can_manage_party(request.user),
        **_flash(request),
    })


@require_POST
@require_login
def document_request(request, pk):
    document = get_object_or_404(PartyDocument, pk=pk)
    try:
        services.request_access(document, request.POST.get('purpose', ''), request.user)
    except services.PartyError as exc:
        return redirect('/r19/documents/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r19/access/?ok={}'.format(quote('借阅申请已提交')))


@require_GET
@require_login
def access_list(request):
    can_manage = services.can_manage_party(request.user)
    services.expire_requests()
    requests = list(services.scoped_access_requests(request.user))
    return render(request, 'r19/access.html', {
        'requests': requests,
        'can_manage': can_manage,
        **_flash(request),
    })


@require_POST
@require_login
def access_action(request, pk, action):
    request_row = get_object_or_404(AccessRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_access(request_row, request.user)
        elif action == 'reject':
            services.reject_access(request_row, request.user,
                                    request.POST.get('reason', ''))
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.PartyError as exc:
        return redirect('/r19/access/?error={}'.format(quote(str(exc))))
    return redirect('/r19/access/?ok={}'.format(quote('操作成功')))


@require_GET
@require_login
def audit_list(request):
    if not services.can_manage_party(request.user):
        return _forbidden(request)
    logs = list(services.scoped_audit_logs(request.user)[:200])
    return render(request, 'r19/audit.html', {
        'logs': logs,
        **_flash(request),
    })


def _parse_pk(raw):
    """把请求参数转成合法主键；非法值返回 None，避免 ValueError 变成 500。"""
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None
