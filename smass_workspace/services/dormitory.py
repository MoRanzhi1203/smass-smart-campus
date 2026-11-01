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
    DormZone,
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
        'zone_options': list(DormZone.objects.order_by('code')),
        'building_options': list(DormBuilding.objects.select_related(
            'building').order_by('building__code')),
        'free_beds': list(dorm_services.available_beds()[:50]),
        'room_rows': _room_rows(limit=40),
    }


def _room_rows(limit=40):
    from django.db.models import Count, Q

    return list(
        DormRoom.objects.select_related('room', 'building__building')
        .annotate(occupied=Count(
            'beds__assignments',
            filter=Q(beds__assignments__active_slot=1), distinct=True))
        .order_by('room__code')[:limit])


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

# ---------------------------------------------------------------------------
# V2.1 管理端：资源创建、分床、导出
# ---------------------------------------------------------------------------
def create_building(zone, code, name, *, floors=6, rooms_per_floor=20,
                    gender='mixed'):
    from smass_facilities.models import Building, Room

    code = (code or '').strip().upper()
    if not code or not name:
        raise dorm_services.DormError('楼栋编码与名称必填', code='EMPTY_FIELD')
    if Building.objects.filter(code=code).exists():
        raise dorm_services.DormError('楼栋编码已存在', code='CODE_EXISTS')
    building = Building.objects.create(
        code=code, name=name, campus=getattr(zone, 'campus', ''))
    dorm_building = DormBuilding.objects.create(
        building=building, zone=zone, floors=floors,
        gender_policy=gender)
    rooms = 0
    for floor in range(1, max(1, floors) + 1):
        for order in range(1, max(1, rooms_per_floor) + 1):
            room_code = '{}-{}{:02d}'.format(code, floor, order)
            if Room.objects.filter(code=room_code).exists():
                continue
            room = Room.objects.create(
                code=room_code, name='寝室{}'.format(room_code.split('-')[-1]),
                building=building, floor=str(floor), capacity=4)
            dorm_room = DormRoom.objects.create(
                room=room, building=dorm_building, capacity=4)
            for number in (1, 2, 3, 4):
                Bed.objects.create(room=dorm_room, number=number)
            rooms += 1
    return {'building': dorm_building, 'rooms': rooms}


def create_room(dorm_building, room_code, *, capacity=4):
    from smass_facilities.models import Room

    room_code = (room_code or '').strip().upper()
    if not room_code:
        raise dorm_services.DormError('房间号必填', code='EMPTY_FIELD')
    if Room.objects.filter(code=room_code).exists():
        raise dorm_services.DormError('房间号已存在', code='CODE_EXISTS')
    room = Room.objects.create(
        code=room_code, name='寝室{}'.format(room_code.split('-')[-1]),
        building=dorm_building.building, capacity=capacity)
    dorm_room = DormRoom.objects.create(
        room=room, building=dorm_building, capacity=capacity)
    for number in range(1, capacity + 1):
        Bed.objects.create(room=dorm_room, number=number)
    return dorm_room


def assign_bed(student_no, bed_id, actor):
    from smass_facilities.models import Building  # noqa: F401 - 保持导入形状
    from smass_organization.models import StudentRecord

    student_no = (student_no or '').strip()
    record = StudentRecord.objects.filter(student_no=student_no).first()
    if record is None:
        raise dorm_services.DormError('学号不存在', code='NO_RECORD')
    bed = Bed.objects.filter(pk=bed_id or 0).first()
    if bed is None:
        raise dorm_services.DormError('床位不存在', code='NO_BED')
    if not dorm_services.can_manage_building(actor, bed.room.building):
        raise dorm_services.DormError('该楼栋不在你的管理范围', code='NO_SCOPE')
    return dorm_services.allocate(record, bed, actor, note='管理端分配')


def export_rows():
    rows = []
    assignments = (DormAssignment.objects.filter(active_slot=1)
                   .select_related('student', 'student__account', 'bed',
                                   'bed__room', 'bed__room__room',
                                   'bed__room__building__building')
                   .order_by('bed__room__building__building__code',
                             'bed__room__room__code', 'bed__number'))
    for item in assignments:
        room = item.bed.room
        rows.append([
            item.student.student_no, item.student.name,
            room.building.building.name, room.room.code,
            item.bed.number,
            item.checkin_at.strftime('%Y-%m-%d') if item.checkin_at else '',
        ])
    return rows

# ---------------------------------------------------------------------------
# V2.1 管理端：状态、批量分床、住宿导入
# ---------------------------------------------------------------------------
def set_room_status(room, status, actor=None):
    valid = dict(DormRoom.STATUS_CHOICES)
    if status not in valid:
        raise dorm_services.DormError('非法寝室状态', code='BAD_STATUS')
    if status != DormRoom.STATUS_OPEN and room.beds.filter(
            assignments__active_slot=1).exists():
        raise dorm_services.DormError('寝室内仍有在住学生，不能停用',
                                      code='ROOM_OCCUPIED')
    room.status = status
    room.save(update_fields=['status'])
    return room


def set_building_status(building, status, actor=None):
    valid = dict(DormBuilding.STATUS_CHOICES)
    if status not in valid:
        raise dorm_services.DormError('非法楼栋状态', code='BAD_STATUS')
    if status != DormBuilding.STATUS_OPEN and building.rooms.filter(
            beds__assignments__active_slot=1).exists():
        raise dorm_services.DormError('楼栋内仍有在住学生，不能停用',
                                      code='BUILDING_OCCUPIED')
    building.status = status
    building.save(update_fields=['status'])
    return building


def batch_assign(class_code, building, actor):
    """把某行政班中尚未住宿的学生按空床顺序分配。"""
    from smass_organization.models import StudentRecord

    class_code = (class_code or '').strip()
    if not class_code:
        raise dorm_services.DormError('请选择班级', code='NO_CLASS')
    students = list(
        StudentRecord.objects.filter(unit__code=class_code)
        .exclude(dorm_assignments__active_slot=1)
        .order_by('student_no'))
    free = list(dorm_services.available_beds(building=building))
    created = 0
    errors = []
    for student, bed in zip(students, free):
        try:
            dorm_services.allocate(student, bed, actor, note='批量分床')
            created += 1
        except dorm_services.DormError as exc:
            errors.append('{}: {}'.format(student.student_no, exc))
    return {'created': created, 'candidates': len(students),
            'free_beds': len(free), 'errors': errors[:10]}


def import_assignments(text, actor):
    """CSV 导入：``学号,房间号,床位号``（首行可为表头）。"""
    from smass_dormitory.models import Bed
    from smass_organization.models import StudentRecord

    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    if not lines:
        raise dorm_services.DormError('文件为空', code='EMPTY_FILE')
    if lines[0].lower().startswith('student'):
        lines = lines[1:]
    created = 0
    errors = []
    for index, line in enumerate(lines, start=2):
        parts = [item.strip() for item in line.split(',')]
        if len(parts) < 3:
            errors.append('第{}行：列数不足'.format(index))
            continue
        student_no, room_code, bed_number = parts[0], parts[1], parts[2]
        record = StudentRecord.objects.filter(student_no=student_no).first()
        if record is None:
            errors.append('第{}行：学号不存在 {}'.format(index, student_no))
            continue
        bed = (Bed.objects.filter(room__room__code=room_code,
                                  number=bed_number).first())
        if bed is None:
            errors.append('第{}行：床位不存在 {}-{}'.format(
                index, room_code, bed_number))
            continue
        try:
            dorm_services.allocate(record, bed, actor, note='CSV 导入')
            created += 1
        except dorm_services.DormError as exc:
            errors.append('第{}行：{}'.format(index, exc))
    return {'created': created, 'total': len(lines), 'errors': errors[:20]}
