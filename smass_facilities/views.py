"""R16 场地预约页面层：房间列表、共享日历、预约、审批、签到/释放。

权限原则
--------
- 所有页面要求登录；
- 预约资格、冲突、容量、维护期由 ``services`` 统一校验，视图不绕过；
- 审批列表只对具备 ``update`` 动作的账号开放；
- 服务层强制"申请人 ≠ 审批人"，本层只负责把错误展示给用户。

视图只做参数解析与渲染，所有写操作都经过 ``services``。
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import (
    BOOKING_PENDING,
    BOOKING_STATUS_CHOICES,
    ROOM_STATUS_CHOICES,
    ROOM_TYPES,
    Building,
    Room,
    RoomBooking,
)

STATUS_LABELS = dict(BOOKING_STATUS_CHOICES)


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


def _parse_dt(raw, *, required=True):
    raw = (raw or '').strip()
    if not raw:
        if required:
            raise ValueError('请填写完整的时间')
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'):
        try:
            value = datetime.strptime(raw, fmt)
            return timezone.make_aware(value)
        except ValueError:
            continue
    raise ValueError('时间格式应为 YYYY-MM-DDTHH:MM')


def _day_bounds(raw_date):
    if raw_date:
        try:
            day = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            day = timezone.localdate()
    else:
        day = timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, dtime.min))
    return day, start, start + timedelta(days=1)


def _room_queryset():
    return Room.objects.select_related('building').filter(is_active=True)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
@require_GET
@require_login
def room_list(request):
    rooms = list(_room_queryset().order_by('building__code', 'code'))
    buildings = list(Building.objects.filter(is_active=True).order_by('code'))

    building_id = request.GET.get('building', '')
    room_type = request.GET.get('room_type', '')
    min_capacity = request.GET.get('min_capacity', '')
    start_raw = request.GET.get('start_at', '')
    end_raw = request.GET.get('end_at', '')
    error = ''

    if building_id:
        rooms = [r for r in rooms if str(r.building_id) == building_id]
    if room_type:
        rooms = [r for r in rooms if r.room_type == room_type]
    if min_capacity:
        try:
            need = int(min_capacity)
            rooms = [r for r in rooms if r.capacity == 0 or r.capacity >= need]
        except ValueError:
            pass

    if start_raw or end_raw:
        try:
            start = _parse_dt(start_raw)
            end = _parse_dt(end_raw)
            available = {r.pk for r in services.available_rooms(
                start, end, room_type=room_type or None)}
            rooms = [r for r in rooms if r.pk in available]
        except (ValueError, services.FacilityError) as exc:
            error = str(exc)

    context = {
        'rooms': rooms,
        'buildings': buildings,
        'room_types': ROOM_TYPES,
        'room_statuses': ROOM_STATUS_CHOICES,
        'filters': {
            'building': building_id, 'room_type': room_type,
            'min_capacity': min_capacity, 'start_at': start_raw,
            'end_at': end_raw,
        },
        'error_message': error or request.GET.get('error', ''),
        'ok_message': request.GET.get('ok', ''),
    }
    return render(request, 'r16/rooms.html', context)


@require_GET
@require_login
def room_detail(request, pk):
    room = get_object_or_404(_room_queryset(), pk=pk)
    day, day_start, day_end = _day_bounds(request.GET.get('date'))
    calendar = services.room_calendar(room, day_start, day_end)
    can_book = services.can_book(request.user, room)
    context = {
        'room': room,
        'day': day,
        'calendar': calendar,
        'can_book': can_book,
        'has_qualification': services.has_qualification(request.user, room),
        'can_approve': services.can_approve(request.user),
        'default_start': '{}T09:00'.format(day.isoformat()),
        'default_end': '{}T10:00'.format(day.isoformat()),
        'error_message': request.GET.get('error', ''),
        'ok_message': request.GET.get('ok', ''),
        'form': {},
    }
    return render(request, 'r16/room_detail.html', context)


@require_GET
@require_login
def shared_calendar(request):
    day, day_start, day_end = _day_bounds(request.GET.get('date'))
    rooms = list(_room_queryset().order_by('building__code', 'code'))
    calendars = []
    for room in rooms:
        cal = services.room_calendar(room, day_start, day_end)
        calendars.append({
            'room': room,
            'bookings': cal['bookings'],
            'maintenances': cal['maintenances'],
        })
    return render(request, 'r16/calendar.html', {
        'day': day,
        'calendars': calendars,
        'status_labels': STATUS_LABELS,
        'error_message': request.GET.get('error', ''),
        'ok_message': request.GET.get('ok', ''),
    })


@require_GET
@require_login
def my_bookings(request):
    bookings = list(
        services.scoped_bookings(request.user)
        .select_related('room', 'room__building', 'account')
        .order_by('-start_at')[:100])
    return render(request, 'r16/bookings.html', {
        'bookings': bookings,
        'status_labels': STATUS_LABELS,
        **_flash(request),
    })


@require_GET
@require_login
def approvals(request):
    if not services.can_approve(request.user):
        return render(request, 'r16/forbidden.html', status=403)
    pending = list(
        RoomBooking.objects.select_related('room', 'room__building', 'account')
        .filter(status=BOOKING_PENDING).order_by('start_at'))
    return render(request, 'r16/approvals.html', {
        'pending': pending,
        'status_labels': STATUS_LABELS,
        'me': request.user,
        **_flash(request),
    })


# ---------------------------------------------------------------------------
# 写操作
# ---------------------------------------------------------------------------
@require_POST
@require_login
def create_booking(request, pk):
    room = get_object_or_404(_room_queryset(), pk=pk)
    day = request.POST.get('date') or timezone.localdate().isoformat()
    form = {
        'start_at': request.POST.get('start_at', ''),
        'end_at': request.POST.get('end_at', ''),
        'purpose': request.POST.get('purpose', ''),
        'attendees': request.POST.get('attendees', ''),
    }
    try:
        start = _parse_dt(form['start_at'])
        end = _parse_dt(form['end_at'])
        attendees = int(form['attendees'] or 0)
        services.create_booking(
            request.user, room, start, end, form['purpose'],
            attendees=attendees, request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:room_detail', args=[room.pk]),
            quote('预约已提交')))
    except (ValueError, services.FacilityError) as exc:
        calendar = services.room_calendar(
            room, *_day_bounds(day)[1:])
        return render(request, 'r16/room_detail.html', status=400, context={
            'room': room,
            'day': _day_bounds(day)[0],
            'calendar': calendar,
            'can_book': services.can_book(request.user, room),
            'has_qualification': services.has_qualification(request.user, room),
            'can_approve': services.can_approve(request.user),
            'default_start': '{}T09:00'.format(day),
            'default_end': '{}T10:00'.format(day),
            'error_message': str(exc),
            'form': form,
        })


def _booking(pk):
    return get_object_or_404(
        RoomBooking.objects.select_related('room', 'account'), pk=pk)


@require_POST
@require_login
def cancel_booking(request, pk):
    booking = _booking(pk)
    try:
        services.cancel_booking(
            booking, request.user, request.POST.get('reason', ''), request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:bookings'), quote('预约已取消')))
    except services.FacilityError as exc:
        return redirect('{}?error={}'.format(
            reverse('r16:bookings'), quote(str(exc))))


@require_POST
@require_login
def check_in(request, pk):
    booking = _booking(pk)
    try:
        services.check_in_booking(booking, request.user, request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:bookings'), quote('签到成功')))
    except services.FacilityError as exc:
        return redirect('{}?error={}'.format(
            reverse('r16:bookings'), quote(str(exc))))


@require_POST
@require_login
def release(request, pk):
    booking = _booking(pk)
    try:
        services.release_booking(booking, request.user, request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:bookings'), quote('已释放房间')))
    except services.FacilityError as exc:
        return redirect('{}?error={}'.format(
            reverse('r16:bookings'), quote(str(exc))))


@require_POST
@require_login
def approve(request, pk):
    booking = _booking(pk)
    try:
        services.approve_booking(booking, request.user, request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:approvals'), quote('已批准')))
    except services.FacilityError as exc:
        return redirect('{}?error={}'.format(
            reverse('r16:approvals'), quote(str(exc))))


@require_POST
@require_login
def reject(request, pk):
    booking = _booking(pk)
    try:
        services.reject_booking(
            booking, request.user, request.POST.get('reason', ''), request=request)
        return redirect('{}?ok={}'.format(
            reverse('r16:approvals'), quote('已驳回')))
    except services.FacilityError as exc:
        return redirect('{}?error={}'.format(
            reverse('r16:approvals'), quote(str(exc))))
