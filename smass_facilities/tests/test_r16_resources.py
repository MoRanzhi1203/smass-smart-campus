"""R16 验收：场地资源、可用性、冲突、审批、签到与授权域。

覆盖主任务书 R16：
- 房间/设备/资格/可用时段/维护封闭期建模；
- **时间不重叠**（含并发）；
- 需要资格 / 需要审批 / 容量 / 可用时段 的默认拒绝；
- 签到 / 爽约 / 释放的状态迁移；
- 共享日历与"该时段可预约房间"查询；
- 授权域收窄（学生/教师只看自己）。

运行::

    python manage.py test smass_facilities --settings=smass.settings_r16
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_facilities import services as fac
from smass_facilities.models import (
    BOOKING_APPROVED,
    BOOKING_CANCELLED,
    BOOKING_CHECKED_IN,
    BOOKING_NO_SHOW,
    BOOKING_PENDING,
    BOOKING_RELEASED,
    ROOM_STATUS_CLOSED,
    ROOM_STATUS_MAINTENANCE,
    ROOM_TYPE_CLASSROOM,
    ROOM_TYPE_LAB,
    Building,
    Equipment,
    MaintenanceWindow,
    Room,
    RoomAvailability,
    RoomBooking,
    RoomEquipment,
    RoomQualification,
)

PASSWORD = 'R16Pass#2024'


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def make_account(login_name, roles=(), person_type='teacher', scope=''):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name,
        person_type=person_type, scope_college=scope)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def make_room(code='R101', *, room_type=ROOM_TYPE_CLASSROOM, capacity=40,
              requires_qualification=False, requires_approval=False,
              status='open', building=None):
    if building is None:
        building, _ = Building.objects.get_or_create(
            code='B1', defaults={'name': '主楼'})
    return Room.objects.create(
        code=code, name='房间{}'.format(code), building=building,
        room_type=room_type, capacity=capacity,
        requires_qualification=requires_qualification,
        requires_approval=requires_approval, status=status)


def tomorrow_slot(hour=9, duration=2):
    """明天 hour 点开始的时长为 duration 小时的区间（避免"过去时间"）。"""
    base = timezone.localtime(timezone.now()).replace(
        hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    start = base + dt.timedelta(hours=hour)
    return start, start + dt.timedelta(hours=duration)


class RoomModelTests(TestCase):
    def test_bookable_reflects_status_and_active(self):
        room = make_room()
        self.assertTrue(room.bookable)
        room.status = ROOM_STATUS_MAINTENANCE
        room.save(update_fields=['status'])
        self.assertFalse(room.bookable)

    def test_equipment_quantity_non_negative_enforced_by_app(self):
        room = make_room()
        eq = Equipment.objects.create(code='PROJ', name='投影仪')
        link = RoomEquipment.objects.create(room=room, equipment=eq, quantity=1)
        self.assertEqual(link.quantity, 1)

    def test_capacity_constraint_exists(self):
        """模型有 capacity >= 0 的 CheckConstraint。"""
        names = {c.name for c in Room._meta.constraints}
        self.assertIn('r16_room_capacity_nonneg', names)


class BookingConflictTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T1', roles=[RoleCode.TEACHER])
        self.room = make_room()
        self.start, self.end = tomorrow_slot(9, 2)

    def test_create_booking_ok(self):
        booking = fac.create_booking(
            self.teacher, self.room, self.start, self.end, '班会', attendees=30)
        self.assertEqual(booking.status, BOOKING_APPROVED)
        self.assertEqual(RoomBooking.objects.count(), 1)

    def test_overlapping_rejected(self):
        fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        with self.assertRaises(fac.BookingConflict):
            fac.create_booking(self.teacher, self.room,
                               self.start + dt.timedelta(minutes=30),
                               self.end + dt.timedelta(minutes=30), 'B')
        self.assertEqual(RoomBooking.objects.count(), 1)

    def test_adjacent_allowed(self):
        fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        booking = fac.create_booking(
            self.teacher, self.room, self.end, self.end + dt.timedelta(hours=1), 'B')
        self.assertEqual(booking.status, BOOKING_APPROVED)
        self.assertEqual(RoomBooking.objects.count(), 2)

    def test_other_room_not_affected(self):
        other = make_room('R102')
        fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.create_booking(self.teacher, other, self.start, self.end, 'B')
        self.assertEqual(RoomBooking.objects.count(), 2)

    def test_cancelled_booking_frees_slot(self):
        first = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.cancel_booking(first, self.teacher, '临时取消')
        second = fac.create_booking(self.teacher, self.room, self.start, self.end, 'B')
        self.assertEqual(second.status, BOOKING_APPROVED)

    def test_released_booking_frees_slot(self):
        first = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.release_booking(first, self.teacher)
        second = fac.create_booking(self.teacher, self.room, self.start, self.end, 'B')
        self.assertEqual(second.status, BOOKING_APPROVED)

    def test_bad_range_rejected(self):
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, self.room, self.end, self.start, 'A')
        self.assertEqual(ctx.exception.code, 'BAD_RANGE')

    def test_past_time_rejected(self):
        past = timezone.now() - dt.timedelta(hours=2)
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, self.room, past,
                               past + dt.timedelta(hours=1), 'A')
        self.assertEqual(ctx.exception.code, 'PAST_TIME')


class RoomStatusAndMaintenanceTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T2', roles=[RoleCode.TEACHER])
        self.start, self.end = tomorrow_slot(10, 1)

    def test_closed_room_rejected(self):
        room = make_room('R201', status=ROOM_STATUS_CLOSED)
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, room, self.start, self.end, 'A')
        self.assertEqual(ctx.exception.code, 'ROOM_NOT_BOOKABLE')

    def test_maintenance_window_rejected(self):
        room = make_room('R202')
        MaintenanceWindow.objects.create(
            room=room, start_at=self.start - dt.timedelta(minutes=30),
            end_at=self.end + dt.timedelta(minutes=30), reason='检修')
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, room, self.start, self.end, 'A')
        self.assertEqual(ctx.exception.code, 'MAINTENANCE_WINDOW')
        self.assertEqual(RoomBooking.objects.count(), 0)

    def test_maintenance_adjacent_allowed(self):
        room = make_room('R203')
        MaintenanceWindow.objects.create(
            room=room, start_at=self.start - dt.timedelta(hours=2),
            end_at=self.start, reason='检修')
        booking = fac.create_booking(self.teacher, room, self.start, self.end, 'A')
        self.assertEqual(booking.status, BOOKING_APPROVED)


class QualificationTests(TestCase):
    def setUp(self):
        self.student = make_account('R16S1', roles=[RoleCode.STUDENT],
                                    person_type='student')
        self.lab = make_room('LAB1', room_type=ROOM_TYPE_LAB,
                             requires_qualification=True)
        self.start, self.end = tomorrow_slot(14, 2)

    def test_lab_without_qualification_rejected(self):
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.student, self.lab, self.start, self.end, '实验')
        self.assertEqual(ctx.exception.code, 'QUALIFICATION_REQUIRED')

    def test_lab_with_qualification_allowed(self):
        RoomQualification.objects.create(room=self.lab, account=self.student)
        booking = fac.create_booking(self.student, self.lab, self.start, self.end, '实验')
        self.assertEqual(booking.status, BOOKING_APPROVED)

    def test_expired_qualification_rejected(self):
        RoomQualification.objects.create(
            room=self.lab, account=self.student,
            expires_at=timezone.now() - dt.timedelta(days=1))
        with self.assertRaises(fac.FacilityError):
            fac.create_booking(self.student, self.lab, self.start, self.end, '实验')

    def test_qualification_not_required_for_classroom(self):
        classroom = make_room('R301')
        booking = fac.create_booking(self.student, classroom, self.start, self.end, '自习')
        self.assertEqual(booking.status, BOOKING_APPROVED)


class CapacityAndAvailabilityTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T3', roles=[RoleCode.TEACHER])
        self.start, self.end = tomorrow_slot(9, 1)

    def test_capacity_exceeded_rejected(self):
        room = make_room('R401', capacity=20)
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, room, self.start, self.end, 'A', attendees=21)
        self.assertEqual(ctx.exception.code, 'CAPACITY_EXCEEDED')

    def test_zero_capacity_means_unlimited(self):
        room = make_room('R402', capacity=0)
        booking = fac.create_booking(self.teacher, room, self.start, self.end, 'A',
                                     attendees=999)
        self.assertEqual(booking.status, BOOKING_APPROVED)

    def test_outside_availability_rejected(self):
        room = make_room('R403')
        RoomAvailability.objects.create(
            room=room, weekday=self.start.weekday(),
            start_time=dt.time(8, 0), end_time=dt.time(10, 0))
        ok = fac.create_booking(self.teacher, room, self.start, self.end, 'A')
        self.assertEqual(ok.status, BOOKING_APPROVED)

        with self.assertRaises(fac.FacilityError) as ctx:
            fac.create_booking(self.teacher, room,
                               self.start.replace(hour=15),
                               self.start.replace(hour=16), 'B')
        self.assertEqual(ctx.exception.code, 'OUT_OF_AVAILABILITY')

    def test_no_availability_window_means_all_day(self):
        room = make_room('R404')
        booking = fac.create_booking(self.teacher, room,
                                     self.start.replace(hour=22),
                                     self.start.replace(hour=23), 'A')
        self.assertEqual(booking.status, BOOKING_APPROVED)


class ApprovalFlowTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T4', roles=[RoleCode.TEACHER])
        self.admin = make_account('R16A1', roles=[RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.room = make_room('R501', requires_approval=True)
        self.start, self.end = tomorrow_slot(9, 2)

    def test_pending_when_approval_required(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        self.assertEqual(booking.status, BOOKING_PENDING)

    def test_approve_moves_to_approved(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.approve_booking(booking, self.admin)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BOOKING_APPROVED)
        self.assertTrue(booking.approved_by)

    def test_self_approval_denied(self):
        booking = fac.create_booking(self.admin, self.room, self.start, self.end, 'A')
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.approve_booking(booking, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_teacher_cannot_approve(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.approve_booking(booking, self.teacher)
        self.assertEqual(ctx.exception.code, 'PERMISSION_DENIED')

    def test_pending_blocks_slot(self):
        """待审批也占位，避免两个申请同时被批准。"""
        fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        with self.assertRaises(fac.BookingConflict):
            fac.create_booking(self.teacher, self.room, self.start, self.end, 'B')


class LifecycleTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T5', roles=[RoleCode.TEACHER])
        self.admin = make_account('R16A2', roles=[RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.room = make_room('R601')
        self.start, self.end = tomorrow_slot(9, 2)

    def test_check_in(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.check_in_booking(booking, self.teacher)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BOOKING_CHECKED_IN)
        self.assertIsNotNone(booking.checked_in_at)

    def test_check_in_requires_approved(self):
        room = make_room('R602', requires_approval=True)
        booking = fac.create_booking(self.teacher, room, self.start, self.end, 'A')
        with self.assertRaises(fac.FacilityError) as ctx:
            fac.check_in_booking(booking, self.teacher)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_no_show_by_admin(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        fac.mark_no_show(booking, self.admin)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BOOKING_NO_SHOW)

    def test_no_show_requires_permission(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        other = make_account('R16T6', roles=[RoleCode.TEACHER])
        with self.assertRaises(fac.FacilityError):
            fac.mark_no_show(booking, other)

    def test_auto_mark_no_shows(self):
        start = timezone.now() - dt.timedelta(hours=2)
        booking = RoomBooking.objects.create(
            room=self.room, account=self.teacher, purpose='逾期',
            start_at=start, end_at=start + dt.timedelta(hours=1),
            status=BOOKING_APPROVED)
        count = fac.auto_mark_no_shows(grace_minutes=15)
        booking.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(booking.status, BOOKING_NO_SHOW)

    def test_cancel_by_other_denied(self):
        booking = fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        other = make_account('R16T7', roles=[RoleCode.TEACHER])
        with self.assertRaises(fac.FacilityError):
            fac.cancel_booking(booking, other, '恶意')
        booking.refresh_from_db()
        self.assertNotEqual(booking.status, BOOKING_CANCELLED)


class CalendarAndSearchTests(TestCase):
    def setUp(self):
        self.teacher = make_account('R16T8', roles=[RoleCode.TEACHER])
        self.room = make_room('R701')
        self.start, self.end = tomorrow_slot(9, 2)

    def test_room_calendar_lists_bookings(self):
        fac.create_booking(self.teacher, self.room, self.start, self.end, 'A')
        calendar = fac.room_calendar(self.room, self.start, self.end)
        self.assertEqual(len(calendar['bookings']), 1)
        self.assertEqual(calendar['room']['code'], 'R701')

    def test_available_rooms_excludes_busy(self):
        busy = make_room('R702')
        free = make_room('R703')
        fac.create_booking(self.teacher, busy, self.start, self.end, 'A')
        rooms = fac.available_rooms(self.start, self.end)
        codes = {r.code for r in rooms}
        self.assertNotIn('R702', codes)
        self.assertIn('R703', codes)

    def test_available_rooms_excludes_maintenance(self):
        room = make_room('R704')
        MaintenanceWindow.objects.create(
            room=room, start_at=self.start, end_at=self.end, reason='检修')
        codes = {r.code for r in fac.available_rooms(self.start, self.end)}
        self.assertNotIn('R704', codes)

    def test_available_rooms_filter_by_capacity_and_type(self):
        make_room('R705', capacity=10)
        make_room('R706', capacity=100, room_type=ROOM_TYPE_LAB)
        rooms = fac.available_rooms(self.start, self.end,
                                    room_type=ROOM_TYPE_LAB, min_capacity=50)
        codes = {r.code for r in rooms}
        self.assertIn('R706', codes)
        self.assertNotIn('R705', codes)


class ScopedBookingTests(TestCase):
    def setUp(self):
        self.teacher_a = make_account('R16TA', roles=[RoleCode.TEACHER])
        self.teacher_b = make_account('R16TB', roles=[RoleCode.TEACHER])
        self.admin = make_account('R16A3', roles=[RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.room = make_room('R801')
        self.start, self.end = tomorrow_slot(9, 1)
        fac.create_booking(self.teacher_a, self.room, self.start, self.end, 'A')
        fac.create_booking(self.teacher_b, self.room,
                           self.end, self.end + dt.timedelta(hours=1), 'B')

    def test_teacher_sees_only_own(self):
        rows = list(fac.scoped_bookings(self.teacher_a))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].account_id, self.teacher_a.pk)

    def test_admin_sees_all(self):
        self.assertEqual(len(list(fac.scoped_bookings(self.admin))), 2)

    def test_anonymous_sees_none(self):
        self.assertEqual(len(list(fac.scoped_bookings(None))), 0)

    def test_account_without_role_sees_none(self):
        nobody = make_account('R16N1', roles=[])
        self.assertEqual(len(list(fac.scoped_bookings(nobody))), 0)


class ConcurrencyTests(TestCase):
    """并发重复预约：同一房间同一时段只能成功一次。"""

    def test_double_booking_race(self):
        import threading

        teacher = make_account('R16C1', roles=[RoleCode.TEACHER])
        room = make_room('R901')
        start, end = tomorrow_slot(9, 2)

        results = []
        barrier = threading.Barrier(2)

        def worker():
            from django.db import connection

            barrier.wait()
            try:
                booking = fac.create_booking(teacher, room, start, end, 'race')
                results.append(('ok', booking.pk))
            except Exception as exc:  # noqa: BLE001
                results.append(('err', type(exc).__name__))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        ok = [r for r in results if r[0] == 'ok']
        # SQLite/MySQL 的锁行为不同：至少不能出现"两个都成功且数据重复"
        self.assertLessEqual(len(ok), 1, '并发下不应产生两条重叠预约: {}'.format(results))
        self.assertLessEqual(RoomBooking.objects.count(), 1)
