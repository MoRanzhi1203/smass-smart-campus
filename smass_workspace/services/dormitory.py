"""V2.1 宿舍产品侧服务：学生住宿视图、宿管工作台、管理端总览与申请入口。"""
from __future__ import annotations

from datetime import date

from django.db.models import Count, Q
from django.utils import timezone

from smass_dormitory import services as dorm_services
from smass_dormitory.models import (
    Bed,
    DormAssignment,
    DormBuilding,
    DormChangeRequest,
    DormCheckoutRequest,
    DormInspection,
    DormManagerScope,
    DormRepair,
    DormRoom,
)


def _assignment_query(record):
    return (DormAssignment.objects
            .filter(student=record, active_slot=1)
            .select_related('bed', 'bed__room', 'bed__room__room',
                            'bed__room__room__building',
                            'bed__room__building__building'))


def student_dormitory(record):
    """学生住宿页数据：在住信息 / 室友 / 历史 / 申请记录 / 未分配原因。"""
    if record is None:
        return {'state': 'no_record', 'assignment': None, 'roommates': []}
    assignment = _assignment_query(record).first()
    extra = record.extra or {}
    dorm_extra = extra.get('dormitory') or {}
    if assignment is None:
        state = 'commute' if dorm_extra.get('mode') == 'commute' else 'unassigned'
        return {
            'state': state,
            'assignment': None,
            'roommates': [],
            'history': list(DormAssignment.objects.filter(
                student=record).order_by('-created_at')[:10]),
            'changes': list(DormChangeRequest.objects.filter(
                student=record).order_by('-created_at')[:10]),
            'checkouts': list(DormCheckoutRequest.objects.filter(
                student=record).order_by('-created_at')[:10]),
            'repairs': list(DormRepair.objects.filter(
                student=record).order_by('-created_at')[:10]),
            'extra': dorm_extra,
        }
    room = assignment.bed.room
    roommates = list(
        DormAssignment.objects.filter(bed__room=room, active_slot=1)
        .exclude(student=record)
        .select_related('student'))
    return {
        'state': 'assigned',
        'assignment': assignment,
        'bed': assignment.bed,
        'room': room,
        'roommates': roommates,
        'history': list(DormAssignment.objects.filter(
            student=record).order_by('-created_at')[:10]),
        'changes': list(DormChangeRequest.objects.filter(
            student=record).order_by('-created_at')[:10]),
        'checkouts': list(DormCheckoutRequest.objects.filter(
            student=record).order_by('-created_at')[:10]),
        'repairs': list(DormRepair.objects.filter(
            student=record).order_by('-created_at')[:10]),
        'extra': dorm_extra,
    }


def scope_buildings(account):
    """宿管可见楼栋：明细范围优先，全局管理员可见全部。"""
    if account is None:
        return DormBuilding.objects.none()
    roles = set(getattr(account, 'active_roles', lambda: [])() or [])
    if 'system_admin' in roles:
        return DormBuilding.objects.all()
    ids = list(DormManagerScope.objects.filter(
        account=account).values_list('building_id', flat=True))
    return DormBuilding.objects.filter(pk__in=ids)


def manager_dashboard(account):
    building_qs = scope_buildings(account)
    buildings = list(building_qs)
    building_ids = [item.pk for item in buildings]
    rooms = DormRoom.objects.filter(building_id__in=building_ids)
    beds = Bed.objects.filter(room__building_id__in=building_ids)
    assignments = DormAssignment.objects.filter(
        active_slot=1, bed__room__building_id__in=building_ids)
    today = timezone.localdate()
    stats = {
        'buildings': len(buildings),
        'rooms': rooms.count(),
        'beds': beds.count(),
        'occupied': assignments.count(),
        'free': beds.filter(status=Bed.STATUS_FREE).count(),
        'checkins_today': assignments.filter(checkin_at__date=today).count(),
        'checkouts_today': DormAssignment.objects.filter(
            bed__room__building_id__in=building_ids,
            checkout_at__date=today).count(),
    }
    per_building = list(
        building_qs.annotate(
            room_count=Count('rooms', distinct=True),
            bed_count=Count('rooms__beds', distinct=True),
            occupied=Count('rooms__beds__assignments',
                           filter=Q(rooms__beds__assignments__active_slot=1),
                           distinct=True),
        ).order_by('building__code'))
    pending_changes = list(
        DormChangeRequest.objects
        .filter(status=DormChangeRequest.STATUS_SUBMITTED,
                to_bed__room__building_id__in=building_ids)
        .select_related('student', 'from_bed__room__room',
                        'to_bed__room__room')[:20])
    pending_checkouts = list(
        DormCheckoutRequest.objects
        .filter(status=DormCheckoutRequest.STATUS_SUBMITTED,
                student__dorm_assignments__bed__room__building_id__in=building_ids)
        .distinct().select_related('student')[:20])
    repairs = list(
        DormRepair.objects
        .filter(room__building_id__in=building_ids)
        .exclude(status__in=[DormRepair.STATUS_DONE, DormRepair.STATUS_CLOSED])
        .select_related('room__room', 'room__building__building')
        .order_by('-created_at')[:20])
    inspections = list(
        DormInspection.objects
        .filter(building_id__in=building_ids, result=DormInspection.RESULT_ISSUE)
        .exclude(status=DormInspection.STATUS_CLOSED)
        .select_related('room__room', 'building__building')
        .order_by('-created_at')[:20])
    return {
        'buildings': buildings,
        'stats': stats,
        'per_building': per_building,
        'pending_changes': pending_changes,
        'pending_checkouts': pending_checkouts,
        'repairs': repairs,
        'inspections': inspections,
    }


def admin_overview():
    stats = {
        'buildings': DormBuilding.objects.count(),
        'rooms': DormRoom.objects.count(),
        'beds': Bed.objects.count(),
        'occupied': DormAssignment.objects.filter(active_slot=1).count(),
        'free': Bed.objects.filter(status=Bed.STATUS_FREE).count(),
        'students': DormAssignment.objects.filter(
            active_slot=1).values('student').distinct().count(),
        'pending_changes': DormChangeRequest.objects.filter(
            status=DormChangeRequest.STATUS_SUBMITTED).count(),
        'pending_checkouts': DormCheckoutRequest.objects.filter(
            status=DormCheckoutRequest.STATUS_SUBMITTED).count(),
        'open_repairs': DormRepair.objects.exclude(
            status__in=[DormRepair.STATUS_DONE, DormRepair.STATUS_CLOSED]).count(),
        'open_inspections': DormInspection.objects.filter(
            result=DormInspection.RESULT_ISSUE).exclude(
            status=DormInspection.STATUS_CLOSED).count(),
    }
    occupancy = round(stats['occupied'] * 100.0 / stats['beds'], 1) if stats['beds'] else 0.0
    return {
        'stats': stats,
        'occupancy': occupancy,
        'zones': list(DormBuilding.objects.select_related(
            'zone', 'building').order_by('building__code')),
        'pending_changes': list(DormChangeRequest.objects.filter(
            status=DormChangeRequest.STATUS_SUBMITTED)
            .select_related('student', 'to_bed__room__room')[:20]),
        'pending_checkouts': list(DormCheckoutRequest.objects.filter(
            status=DormCheckoutRequest.STATUS_SUBMITTED)
            .select_related('student')[:20]),
        'repairs': list(DormRepair.objects.exclude(
            status__in=[DormRepair.STATUS_DONE, DormRepair.STATUS_CLOSED])
            .select_related('room__room')[:20]),
        'inspections': list(DormInspection.objects.filter(
            result=DormInspection.RESULT_ISSUE)
            .exclude(status=DormInspection.STATUS_CLOSED)
            .select_related('room__room', 'building__building')[:20]),
        'scopes': list(DormManagerScope.objects.select_related(
            'account', 'building__building').order_by('building__building__code')),
    }


def rooms_in(building, keyword=''):
    queryset = (DormRoom.objects.filter(building=building)
                .select_related('room', 'building__building')
                .annotate(occupied=Count(
                    'beds__assignments',
                    filter=Q(beds__assignments__active_slot=1), distinct=True))
                .order_by('room__code'))
    keyword = (keyword or '').strip()
    if keyword:
        queryset = queryset.filter(room__code__icontains=keyword)
    return list(queryset)


def request_repair(record, description, account):
    assignment = _assignment_query(record).first()
    if assignment is None:
        raise dorm_services.DormError('当前没有在住寝室，无法报修', code='NO_ASSIGNMENT')
    return dorm_services.create_repair(
        assignment.bed.room, description, account,
        bed=assignment.bed, student=record)


def request_change(record, to_bed, reason, account):
    return dorm_services.request_change(record, to_bed, reason, account)


def request_checkout(record, reason, account):
    return dorm_services.request_checkout(record, reason, account)


def available_beds_for(record):
    assignment = _assignment_query(record).first()
    queryset = dorm_services.available_beds()
    if assignment is not None:
        queryset = queryset.exclude(room=assignment.bed.room)
    return list(queryset[:20])
