"""宿舍服务测试（隔离仿真配置：``smass.settings_simulation``）。"""
from __future__ import annotations

from django.test import TestCase

from r21_account.models import Account
from smass_dormitory import services
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


class DormFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Account.objects.create_user(
            'sim_dorm_admin', 'Test#2026pass', display_name='宿舍主管',
            person_type='admin')
        cls.manager = Account.objects.create_user(
            'sim_dorm_manager', 'Test#2026pass', display_name='楼管',
            person_type='admin')
        cls.students = []
        for index in range(6):
            account = Account.objects.create_user(
                'sim_dorm_student_{}'.format(index), 'Test#2026pass',
                display_name='住宿学生{}'.format(index), person_type='student')
            record = StudentRecord.objects.create(
                student_no='SIMD{:06d}'.format(index), name='住宿学生{}'.format(index),
                account=account, status='enrolled')
            cls.students.append((account, record))

        cls.building = Building.objects.create(
            code='SIM-DORM-A', name='仿真一号楼', campus='主校区')
        cls.zone = DormZone.objects.create(code='SIM-ZONE-A', name='东区宿舍',
                                           campus='主校区')
        cls.dorm_building = DormBuilding.objects.create(
            building=cls.building, zone=cls.zone, floors=6)
        cls.rooms = []
        for index in range(2):
            room = Room.objects.create(
                code='SIM-A-{}'.format(101 + index), name='仿真寝室',
                building=cls.building, floor='1', capacity=4)
            dorm_room = DormRoom.objects.create(
                room=room, building=cls.dorm_building, capacity=4)
            beds = [Bed.objects.create(room=dorm_room, number=number)
                    for number in (1, 2, 3, 4)]
            cls.rooms.append((room, dorm_room, beds))
        DormManagerScope.objects.create(
            account=cls.manager, building=cls.dorm_building, role='manager')


class AllocationTests(DormFixture):
    def test_allocate_marks_bed_occupied(self):
        student = self.students[0][1]
        bed = self.rooms[0][2][0]
        assignment = services.allocate(student, bed, self.admin, batch_code='sim-1')
        self.assertEqual(assignment.status, 'active')
        self.assertEqual(assignment.active_slot, 1)
        self.assertEqual(Bed.objects.get(pk=bed.pk).status, 'occupied')
        self.assertEqual(services.active_assignment(student).pk, assignment.pk)

    def test_duplicate_student_rejected(self):
        student = self.students[0][1]
        services.allocate(student, self.rooms[0][2][0], self.admin)
        with self.assertRaises(services.DormError):
            services.allocate(student, self.rooms[0][2][1], self.admin)

    def test_bed_taken_rejected(self):
        services.allocate(self.students[0][1], self.rooms[0][2][0], self.admin)
        with self.assertRaises(services.DormError):
            services.allocate(self.students[1][1], self.rooms[0][2][0], self.admin)

    def test_room_full_rejected(self):
        room = Room.objects.create(
            code='SIM-A-201', name='小寝室', building=self.building,
            floor='2', capacity=4)
        dorm_room = DormRoom.objects.create(
            room=room, building=self.dorm_building, capacity=4)
        beds = [Bed.objects.create(room=dorm_room, number=number)
                for number in (1, 2, 3, 4)]
        # 把容量收窄到 2，模拟“床位多于可住容量”的边界
        dorm_room.capacity = 2
        dorm_room.save(update_fields=['capacity'])
        services.allocate(self.students[0][1], beds[0], self.admin)
        services.allocate(self.students[1][1], beds[1], self.admin)
        with self.assertRaises(services.DormError) as ctx:
            services.allocate(self.students[2][1], beds[2], self.admin)
        self.assertEqual(ctx.exception.code, 'ROOM_FULL')


class ChangeAndCheckoutTests(DormFixture):
    def test_change_approve_swaps_beds(self):
        student = self.students[0][1]
        services.allocate(student, self.rooms[0][2][0], self.admin)
        target = self.rooms[1][2][0]
        request_obj = services.request_change(student, target, '换楼层', self.admin)
        services.approve_change(request_obj, self.manager)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, 'completed')
        self.assertEqual(Bed.objects.get(pk=self.rooms[0][2][0].pk).status, 'free')
        self.assertEqual(Bed.objects.get(pk=target.pk).status, 'occupied')
        self.assertEqual(DormAssignment.objects.filter(
            student=student, active_slot=1).count(), 1)
        self.assertEqual(DormAssignment.objects.filter(
            student=student, status='checked_out').count(), 1)

    def test_change_to_taken_bed_rejected(self):
        student = self.students[0][1]
        other = self.students[1][1]
        services.allocate(student, self.rooms[0][2][0], self.admin)
        services.allocate(other, self.rooms[1][2][0], self.admin)
        request_obj = services.request_change(
            student, self.rooms[1][2][0], '换楼', self.admin)
        with self.assertRaises(services.DormError):
            services.approve_change(request_obj, self.manager)

    def test_checkout_releases_bed(self):
        student = self.students[0][1]
        bed = self.rooms[0][2][0]
        services.allocate(student, bed, self.admin)
        request_obj = services.request_checkout(student, '毕业退宿', self.admin)
        services.approve_checkout(request_obj, self.manager)
        self.assertEqual(Bed.objects.get(pk=bed.pk).status, 'free')
        self.assertIsNone(services.active_assignment(student))


class RepairAndInspectionTests(DormFixture):
    def test_repair_state_machine(self):
        room, dorm_room, _beds = self.rooms[0]
        repair = services.create_repair(
            dorm_room, '水龙头漏水', self.students[0][0],
            student=self.students[0][1])
        services.advance_repair(repair, self.manager, assignee='维修甲')
        services.advance_repair(repair, self.manager)
        services.advance_repair(repair, self.manager)
        repair.refresh_from_db()
        self.assertEqual(repair.status, DormRepair.STATUS_DONE)
        self.assertIsNotNone(repair.done_at)
        services.advance_repair(repair, self.manager)
        with self.assertRaises(services.DormError):
            services.advance_repair(repair, self.manager)

    def test_inspection_requires_issue_text(self):
        with self.assertRaises(services.DormError):
            services.record_inspection(
                self.dorm_building, result='issue', items={'fire': 'ok'})
        inspection = services.record_inspection(
            self.dorm_building, result='ok', items={'fire': 'ok'})
        services.advance_inspection(inspection, self.manager)
        services.advance_inspection(inspection, self.manager)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, DormInspection.STATUS_CLOSED)


class ScopeTests(DormFixture):
    def test_manager_scope_limits_buildings(self):
        self.assertTrue(
            services.can_manage_building(self.manager, self.dorm_building))
        other_building = Building.objects.create(
            code='SIM-DORM-B', name='仿真二号楼', campus='主校区')
        other = DormBuilding.objects.create(
            building=other_building, zone=self.zone)
        self.assertFalse(services.can_manage_building(self.manager, other))
        self.assertEqual(
            list(services.staff_buildings(self.manager)), [self.dorm_building])
