"""P5 宿舍仿真：按住宿需求反推楼栋/房间/床位，生成分配、调宿、退宿、报修、巡查。

容量计算：住宿学生 = 学生数 × 住宿比例；房间数 = ceil(住宿学生/4 × 1.05)（预留空床）；
楼栋数 = ceil(房间数 / 每栋房间数)。楼栋与房间分别复用 facilities.Building/Room。
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from r21_account.models import Account, AccountRole, RoleCode
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
from smass_facilities.models import Building, Room
from smass_organization.models import StudentRecord

from . import names
from .people import password
from .rng import Rng

RESIDENCE_RATIO = 0.85
BED_CAPACITY = 4
ROOMS_PER_BUILDING = 120
FLOORS = 6
SPARE_RATIO = 0.05
BATCH_SIZE = 500


def capacity_plan(students):
    residents = int(round(students * RESIDENCE_RATIO))
    rooms_needed = int(math.ceil(residents / BED_CAPACITY * (1 + SPARE_RATIO)))
    buildings = max(1, int(math.ceil(rooms_needed / ROOMS_PER_BUILDING)))
    return {'students': students, 'residents': residents,
            'rooms': buildings * ROOMS_PER_BUILDING,
            'beds': buildings * ROOMS_PER_BUILDING * BED_CAPACITY,
            'buildings': buildings}


def generate_dorms(config, ctx, *, dry_run=False):
    students = list(StudentRecord.objects.filter(
        student_no__startswith='S', unit__code__startswith='SIM-CLS-')
        .select_related('unit').order_by('unit__code', 'student_no'))
    plan = capacity_plan(len(students))
    if dry_run:
        return dict(plan, dry_run=True, assignments=0)

    rng = Rng(0, 'dorms')
    zone, _ = DormZone.objects.update_or_create(
        code='SIM-ZONE-D', defaults={'name': '仿真东区宿舍', 'campus': '主校区'})
    buildings = []
    for index in range(plan['buildings']):
        code = 'SIM-DORM-B{:02d}'.format(index + 1)
        base, _ = Building.objects.update_or_create(
            code=code, defaults={'name': '仿真宿舍{}号楼'.format(index + 1),
                                 'campus': '主校区'})
        dorm_building, _ = DormBuilding.objects.update_or_create(
            building=base, defaults={
                'zone': zone, 'floors': FLOORS,
                'gender_policy': DormBuilding.GENDER_MIXED,
                'status': DormBuilding.STATUS_OPEN})
        buildings.append(dorm_building)

    rooms = _ensure_rooms(buildings)
    beds = _ensure_beds(rooms)

    assignments = _assign(students, beds, plan, ctx)
    change_requests, checkout_requests = _requests(students, rng)
    repairs, inspections = _repairs_and_inspections(rooms, students[:80], rng)
    staff_count = _staff(buildings, ctx)

    ctx.stage_done('dorms', {
        'buildings': len(buildings), 'rooms': len(rooms),
        'beds': len(beds), 'assignments': assignments,
        'staff': staff_count,
    })
    return dict(plan, buildings_created=len(buildings),
                rooms_created=len(rooms), beds_created=len(beds),
                assignments=assignments, dorm_staff=staff_count,
                change_requests=change_requests,
                checkout_requests=checkout_requests,
                repairs=repairs, inspections=inspections)


def _ensure_rooms(buildings):
    rooms = []
    for building in buildings:
        existing = {room.code: room for room in Room.objects.filter(
            building=building.building)}
        for index in range(ROOMS_PER_BUILDING):
            floor = index // (ROOMS_PER_BUILDING // FLOORS) + 1
            room_no = floor * 100 + (index % (ROOMS_PER_BUILDING // FLOORS)) + 1
            code = '{}-{}'.format(building.building.code, room_no)
            room = existing.get(code)
            if room is None:
                room = Room.objects.create(
                    code=code, name='寝室{}'.format(room_no),
                    building=building.building, floor=str(floor),
                    capacity=BED_CAPACITY)
            dorm_room, _ = DormRoom.objects.update_or_create(
                room=room, defaults={
                    'building': building, 'capacity': BED_CAPACITY,
                    'status': DormRoom.STATUS_OPEN})
            rooms.append(dorm_room)
    return rooms


def _ensure_beds(rooms):
    existing = set(Bed.objects.filter(
        room__in=rooms).values_list('room_id', 'number'))
    new_beds = []
    for room in rooms:
        for number in range(1, BED_CAPACITY + 1):
            if (room.pk, number) not in existing:
                new_beds.append(Bed(room=room, number=number))
    if new_beds:
        Bed.objects.bulk_create(new_beds, batch_size=BATCH_SIZE)
    return list(Bed.objects.filter(room__in=rooms).order_by(
        'room__room__code', 'number'))


def _assign(students, beds, plan, ctx):
    residents = students[:plan['residents']]
    bed_pool = [bed for bed in beds]
    existing = set(DormAssignment.objects.filter(
        student__in=residents, active_slot=1).values_list('student_id',
                                                          flat=True))
    pending = [student for student in residents
               if student.pk not in existing]
    if not pending:
        return DormAssignment.objects.filter(active_slot=1).count()

    free_beds = [bed for bed in bed_pool if bed.status == Bed.STATUS_FREE]
    rows = []
    used = []
    for student, bed in zip(pending, free_beds):
        rows.append(DormAssignment(
            student=student, bed=bed, status=DormAssignment.STATUS_ACTIVE,
            active_slot=1, checkin_at=timezone.now(),
            batch_code=ctx.code))
        used.append(bed.pk)
        if len(rows) >= BATCH_SIZE:
            DormAssignment.objects.bulk_create(rows, batch_size=BATCH_SIZE)
            Bed.objects.filter(pk__in=used).update(status=Bed.STATUS_OCCUPIED)
            rows, used = [], []
    if rows:
        DormAssignment.objects.bulk_create(rows, batch_size=BATCH_SIZE)
        Bed.objects.filter(pk__in=used).update(status=Bed.STATUS_OCCUPIED)
    return DormAssignment.objects.filter(active_slot=1).count()


def _requests(students, rng):
    """少量调宿/退宿记录，覆盖已批准、待审、驳回。"""
    DormChangeRequest.objects.filter(
        student__student_no__startswith='S').delete()
    DormCheckoutRequest.objects.filter(
        student__student_no__startswith='S').delete()
    sample = rng.sample(list(students), min(60, len(students)))
    changes = 0
    checkouts = 0
    for index, student in enumerate(sample[:40]):
        assignment = dorm_services.active_assignment(student)
        if assignment is None:
            continue
        free = dorm_services.available_beds()[:1]
        if not free:
            break
        status = ('completed', 'submitted', 'rejected')[index % 3]
        DormChangeRequest.objects.create(
            student=student, from_bed=assignment.bed, to_bed=free[0],
            reason='仿真调宿申请', status=status,
            submitted_by='sim_student', reviewed_by='sim_dorm_manager',
            reviewed_at=timezone.now() if status != 'submitted' else None,
            reject_reason='床位调整周期已满' if status == 'rejected' else '')
        changes += 1
    for index, student in enumerate(sample[40:60]):
        assignment = dorm_services.active_assignment(student)
        if assignment is None:
            continue
        DormCheckoutRequest.objects.create(
            student=student, assignment=assignment, reason='仿真退宿申请',
            status='submitted' if index % 2 else 'completed',
            reviewed_by='sim_dorm_manager',
            reviewed_at=timezone.now())
        checkouts += 1
    return changes, checkouts


def _repairs_and_inspections(rooms, students, rng):
    DormRepair.objects.filter(room__room__code__startswith='SIM-DORM-').delete()
    DormInspection.objects.filter(
        building__building__code__startswith='SIM-DORM-').delete()
    statuses = [DormRepair.STATUS_SUBMITTED, DormRepair.STATUS_ASSIGNED,
                DormRepair.STATUS_PROCESSING, DormRepair.STATUS_DONE,
                DormRepair.STATUS_CLOSED]
    repairs = 0
    for index, room in enumerate(rooms[:60]):
        DormRepair.objects.create(
            room=room, description='仿真报修：{}'.format(
                rng.choice(['水龙头漏水', '灯管损坏', '门锁松动', '空调异响'])),
            status=statuses[index % len(statuses)],
            assignee='sim_dorm_repair' if index % len(statuses) else '',
            created_by='sim_student')
        repairs += 1
    inspections = 0
    for index, room in enumerate(rooms[:40]):
        result = DormInspection.RESULT_ISSUE if index % 5 == 0 else DormInspection.RESULT_OK
        DormInspection.objects.create(
            building=room.building, room=room,
            items={'fire': 'ok', 'hygiene': 'ok' if result == 'ok' else 'issue'},
            result=result,
            issue='卫生不达标' if result == 'issue' else '',
            status=['recorded', 'rectifying', 'closed'][index % 3],
            inspector='sim_dorm_manager')
        inspections += 1
    return repairs, inspections


def _staff(buildings, ctx):
    hashed = make_password(password())
    accounts = []
    for index, building in enumerate(buildings):
        login = 'sim_dorm_m{:02d}'.format(index + 1)
        if Account.objects.filter(login_name=login).exists():
            continue
        accounts.append(Account(
            login_name=login,
            display_name='{}宿管'.format(index + 1),
            person_type='admin', password=hashed, is_active=True,
            must_change_password=False))
    for login, name in (('sim_dorm_supervisor', '宿舍主管'),
                        ('sim_dorm_repair', '维修员')):
        if Account.objects.filter(login_name=login).exists():
            continue
        accounts.append(Account(login_name=login, display_name=name,
                                person_type='admin', password=hashed,
                                is_active=True, must_change_password=False))
    Account.objects.bulk_create(accounts, batch_size=BATCH_SIZE)
    logins = [item.login_name for item in accounts]
    id_map = dict(Account.objects.filter(
        login_name__in=logins).values_list('login_name', 'pk'))
    roles = [AccountRole(account_id=pk, role=RoleCode.COLLEGE_ADMIN)
             for pk in id_map.values()]
    AccountRole.objects.bulk_create(roles, ignore_conflicts=True,
                                    batch_size=BATCH_SIZE)
    scopes = []
    for index, building in enumerate(buildings):
        pk = id_map.get('sim_dorm_m{:02d}'.format(index + 1))
        if pk:
            scopes.append(DormManagerScope(
                account_id=pk, building=building,
                role=DormManagerScope.ROLE_MANAGER))
    supervisor = id_map.get('sim_dorm_supervisor')
    repair = id_map.get('sim_dorm_repair')
    if supervisor:
        scopes.append(DormManagerScope(
            account_id=supervisor, building=buildings[0],
            role=DormManagerScope.ROLE_SUPERVISOR))
    if repair:
        scopes.append(DormManagerScope(
            account_id=repair, building=buildings[0],
            role=DormManagerScope.ROLE_REPAIR))
    DormManagerScope.objects.bulk_create(scopes, ignore_conflicts=True,
                                         batch_size=BATCH_SIZE)
    for pk in id_map.values():
        ctx.remember('r21_account.Account', pk)
    ctx.flush()
    return len(id_map)
