"""R18 页面层：账单、合成缴费、受控退费与台账。

权限原则
--------
- 学生只看自己的账单与退费，可发起退费申请；
- 财务管理员（system_admin / college_admin）可创建项目、生成账单、登记缴费、
  审批退费、执行退费、查看台账；
- 页面显著标注"合成演练，不接真实支付"。
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
    FEE_CATEGORIES,
    PAYMENT_METHODS,
    Bill,
    FeeItem,
    RefundRequest,
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
    return render(request, 'r18/forbidden.html', {'message': message}, status=403)


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
def bill_list(request):
    can_finance = services.can_finance(request.user)
    bills = list(services.scoped_bills(request.user)[:100])
    my_record = None
    summary = None
    if not can_finance:
        my_record = StudentRecord.objects.filter(account=request.user).first()
        summary = services.bill_summary(my_record) if my_record else None
    return render(request, 'r18/bills.html', {
        'bills': bills,
        'can_finance': can_finance,
        'summary': summary,
        'fee_items': list(FeeItem.objects.filter(status='active').order_by('term', 'code')),
        'records': list(StudentRecord.objects.order_by('student_no')[:200]) if can_finance else [],
        'fee_categories': FEE_CATEGORIES,
        'finance_totals': services.finance_totals() if can_finance else None,
        **_flash(request),
    })


@require_POST
@require_login
def fee_item_create(request):
    if not services.can_finance(request.user):
        return _forbidden(request)
    try:
        services.create_fee_item(
            request.user, request.POST.get('code', ''), request.POST.get('name', ''),
            (request.POST.get('category') or '').strip(),
            request.POST.get('amount') or 0,
            term=request.POST.get('term', ''))
    except services.FinanceError as exc:
        return redirect('/r18/bills/?error={}'.format(quote(str(exc))))
    return redirect('/r18/bills/?ok={}'.format(quote('收费项目已创建')))


@require_POST
@require_login
def bill_create(request):
    if not services.can_finance(request.user):
        return _forbidden(request)
    record = StudentRecord.objects.filter(
        pk=_parse_pk(request.POST.get('record'))).first()
    item = FeeItem.objects.filter(
        pk=_parse_pk(request.POST.get('fee_item'))).first()
    try:
        services.create_bill(
            record, request.POST.get('term', ''), [item] if item else [],
            request.user, due_date=_parse_date(request.POST.get('due_date')))
    except services.FinanceError as exc:
        return redirect('/r18/bills/?error={}'.format(quote(str(exc))))
    return redirect('/r18/bills/?ok={}'.format(quote('账单已生成')))


@require_GET
@require_login
def bill_detail(request, pk):
    bill = get_object_or_404(Bill.objects.select_related('record'), pk=pk)
    can_finance = services.can_finance(request.user)
    is_owner = str(getattr(bill.record.account, 'pk', '')) == str(
        getattr(request.user, 'pk', ''))
    if not can_finance and not is_owner:
        return _forbidden(request, '只能查看自己的账单')
    return render(request, 'r18/bill_detail.html', {
        'bill': bill,
        'items': list(bill.items.select_related('fee_item')),
        'payments': list(bill.payments.order_by('-created_at')),
        'refunds': list(bill.refunds.order_by('-created_at')),
        'can_finance': can_finance,
        'is_owner': is_owner,
        'payment_methods': PAYMENT_METHODS,
        **_flash(request),
    })


@require_POST
@require_login
def bill_pay(request, pk):
    if not services.can_finance(request.user):
        return _forbidden(request)
    bill = get_object_or_404(Bill, pk=pk)
    try:
        services.pay_bill(
            bill, request.POST.get('amount') or 0, request.user,
            method=(request.POST.get('method') or 'synthetic_bank').strip(),
            reference=request.POST.get('reference', ''),
            note=request.POST.get('note', ''))
    except services.FinanceError as exc:
        return redirect('/r18/bills/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r18/bills/{}/?ok={}'.format(pk, quote('合成缴费已登记')))


@require_POST
@require_login
def refund_request(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    try:
        services.request_refund(
            bill, request.POST.get('amount') or 0,
            request.POST.get('reason', ''), request.user)
    except services.PermissionDenied:
        return _forbidden(request)
    except services.FinanceError as exc:
        return redirect('/r18/bills/{}/?error={}'.format(pk, quote(str(exc))))
    return redirect('/r18/bills/{}/?ok={}'.format(pk, quote('退费申请已提交')))


@require_GET
@require_login
def refund_list(request):
    can_finance = services.can_finance(request.user)
    refunds = list(services.scoped_refunds(request.user)[:100])
    return render(request, 'r18/refunds.html', {
        'refunds': refunds,
        'can_finance': can_finance,
        **_flash(request),
    })


@require_POST
@require_login
def refund_action(request, pk, action):
    refund = get_object_or_404(RefundRequest, pk=pk)
    try:
        if action == 'approve':
            services.approve_refund(refund, request.user)
        elif action == 'reject':
            services.reject_refund(refund, request.user, request.POST.get('reason', ''))
        elif action == 'execute':
            services.execute_refund(refund, request.user)
        else:
            return _forbidden(request, '未知操作')
    except services.PermissionDenied:
        return _forbidden(request)
    except services.FinanceError as exc:
        return redirect('/r18/refunds/?error={}'.format(quote(str(exc))))
    return redirect('/r18/refunds/?ok={}'.format(quote('操作成功')))


@require_GET
@require_login
def ledger_list(request):
    if not services.can_finance(request.user):
        return _forbidden(request)
    entries = list(services.scoped_ledger(request.user)[:200])
    return render(request, 'r18/ledger.html', {
        'entries': entries,
        'totals': services.finance_totals(),
        **_flash(request),
    })


def _parse_pk(raw):
    """把请求参数转成合法主键；非法值返回 None，避免 ValueError 变成 500。"""
    text = str(raw or '').strip()
    return int(text) if text.isdigit() else None
