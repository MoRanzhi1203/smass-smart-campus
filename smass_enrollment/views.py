"""R12 学籍管理页面层：分班、转专业、学籍异动。

权限原则
--------
- 所有页面要求登录；
- 分班（规则/预览/执行/回滚）只对教务管理员开放，其余一律 403；
- 转专业与学籍异动：学生只能看到并提交自己的，管理员可看全部；
- 审批禁止自批、非法状态迁移由 ``services`` 统一拒绝，本层只做展示。
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from smass_organization.models import StudentRecord

from . import services
from .models import (
    CHANGE_TYPES,
    MajorTransferRequest,
    PlacementBatch,
    PlacementRule,
    StudentStatusChange,
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
    return render(request, 'r12/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


def _majors():
    from smass_organization.models import UNIT_TYPE_MAJOR, OrganizationUnit
    return OrganizationUnit.objects.filter(
        unit_type=UNIT_TYPE_MAJOR, status='active').order_by('code')


# ---------------------------------------------------------------------------
# 分班
# ---------------------------------------------------------------------------
@require_GET
@require_login
def placement_list(request):
    if not services.can_manage(request.user):
        return _forbidden(request)
    rules = list(PlacementRule.objects.select_related('major').order_by('major__code', 'name'))
    summaries = [services.placement_summary(rule) for rule in rules]
    batches = list(PlacementBatch.objects.select_related('rule').order_by('-created_at')[:20])
    return render(request, 'r12/placement_list.html', {
        'summaries': summaries,
        'batches': batches,
        **_flash(request),
    })


@require_POST
@require_login
def placement_preview(request, rule_id):
    if not services.can_manage(request.user):
        return _forbidden(request)
    rule = get_object_or_404(PlacementRule, pk=rule_id)
    try:
        batch = services.create_placement_preview(rule, request.user)
    except services.EnrollmentError as exc:
        return redirect('/r12/placement/?error={}'.format(quote(str(exc))))
    return redirect('/r12/placement/{}/?ok={}'.format(
        batch.pk, quote('已生成预览，请核对后执行')))


@require_GET
@require_login
def placement_detail(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    batch = get_object_or_404(PlacementBatch.objects.select_related('rule', 'rule__major'), pk=pk)
    return render(request, 'r12/placement_detail.html', {
        'batch': batch,
        'rows': services.batch_rows(batch),
        **_flash(request),
    })


@require_POST
@require_login
def placement_apply(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    batch = get_object_or_404(PlacementBatch, pk=pk)
    try:
        services.apply_placement(batch, request.user)
    except services.EnrollmentError as exc:
        return redirect('/r12/placement/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r12/placement/{}/?ok={}'.format(pk, quote('分班已执行')))


@require_POST
@require_login
def placement_rollback(request, pk):
    if not services.can_manage(request.user):
        return _forbidden(request)
    batch = get_object_or_404(PlacementBatch, pk=pk)
    try:
        services.rollback_placement(batch, request.user)
    except services.EnrollmentError as exc:
        return redirect('/r12/placement/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r12/placement/{}/?ok={}'.format(pk, quote('分班已回滚')))


# ---------------------------------------------------------------------------
# 转专业
# ---------------------------------------------------------------------------
@require_GET
@require_login
def transfer_list(request):
    can_manage = services.can_manage(request.user)
    transfers = list(services.scoped_transfers(request.user).order_by('-created_at')[:100])
    my_record = services.record_for_account(request.user)
    rows = [
        {'t': transfer, 'classes': list(services.classes_of_major(transfer.to_major))}
        for transfer in transfers
    ]
    records_for_admin = []
    if can_manage:
        records_for_admin = list(
            StudentRecord.objects.order_by('student_no')[:200])
    return render(request, 'r12/transfers.html', {
        'rows': rows,
        'transfers': transfers,
        'can_manage': can_manage,
        'majors': list(_majors()),
        'my_record': my_record,
        'records_for_admin': records_for_admin,
        **_flash(request),
    })


@require_POST
@require_login
def transfer_submit(request):
    record_id = (request.POST.get('record_id') or '').strip()
    if services.can_manage(request.user) and record_id:
        record = StudentRecord.objects.filter(pk=record_id).first()
    else:
        record = services.record_for_account(request.user)
    if record is None:
        return redirect('/r12/transfers/?error={}'.format(
            quote('未找到可申请转专业的学籍档案')))
    to_major = _majors().filter(pk=request.POST.get('to_major') or 0).first()
    try:
        services.submit_transfer(
            record, to_major, request.POST.get('reason', ''), request.user)
    except services.EnrollmentError as exc:
        return redirect('/r12/transfers/?error={}'.format(quote(str(exc))))
    return redirect('/r12/transfers/?ok={}'.format(quote('转专业申请已提交')))


@require_POST
@require_login
def transfer_action(request, pk, action):
    transfer = get_object_or_404(MajorTransferRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_transfer(transfer, request.user)
        elif action == 'reject':
            services.reject_transfer(transfer, request.user, request.POST.get('reason', ''))
        elif action == 'apply':
            target = _classes_of(transfer.to_major).filter(
                pk=request.POST.get('target_class') or 0).first()
            services.apply_transfer(transfer, request.user, target)
        elif action == 'cancel':
            if transfer.record.account_id != getattr(request.user, 'pk', None):
                return _forbidden(request, '只能撤销自己的申请')
            services.cancel_transfer(transfer, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.EnrollmentError as exc:
        return redirect('/r12/transfers/?error={}'.format(quote(str(exc))))
    return redirect('/r12/transfers/?ok={}'.format(quote('操作成功')))


def _classes_of(major):
    return services.classes_of_major(major)


# ---------------------------------------------------------------------------
# 学籍异动
# ---------------------------------------------------------------------------
@require_GET
@require_login
def status_list(request):
    can_manage = services.can_manage(request.user)
    changes = list(services.scoped_status_changes(request.user).order_by('-created_at')[:100])
    my_record = services.record_for_account(request.user)
    records = []
    if can_manage:
        records = list(StudentRecord.objects.select_related('unit').order_by('student_no')[:200])
    return render(request, 'r12/status.html', {
        'changes': changes,
        'can_manage': can_manage,
        'my_record': my_record,
        'records': records,
        'change_types': CHANGE_TYPES,
        **_flash(request),
    })


@require_POST
@require_login
def status_submit(request):
    record_id = (request.POST.get('record_id') or '').strip()
    if services.can_manage(request.user) and record_id:
        record = StudentRecord.objects.filter(pk=record_id).first()
    else:
        record = services.record_for_account(request.user)
    if record is None:
        return redirect('/r12/status/?error={}'.format(quote('未找到学籍档案')))
    try:
        services.submit_status_change(
            record,
            (request.POST.get('change_type') or '').strip(),
            request.POST.get('reason', ''),
            request.user,
        )
    except services.EnrollmentError as exc:
        return redirect('/r12/status/?error={}'.format(quote(str(exc))))
    return redirect('/r12/status/?ok={}'.format(quote('学籍异动申请已提交')))


@require_POST
@require_login
def status_action(request, pk, action):
    change = get_object_or_404(StudentStatusChange, pk=pk)
    try:
        if action == 'approve':
            services.approve_status_change(change, request.user)
        elif action == 'reject':
            services.reject_status_change(change, request.user, request.POST.get('reason', ''))
        elif action == 'apply':
            services.apply_status_change(change, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.EnrollmentError as exc:
        return redirect('/r12/status/?error={}'.format(quote(str(exc))))
    return redirect('/r12/status/?ok={}'.format(quote('操作成功')))
