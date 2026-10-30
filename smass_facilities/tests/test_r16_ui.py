"""R16-UI：场地预约页面的真实业务流程测试。

覆盖：房间列表/筛选、共享日历、预约（待审批）、冲突提示、审批与禁止自批、
驳回必须填原因、签到、释放、越权取消、审批页权限。

运行::

    python manage.py test smass_facilities.tests.test_r16_ui --settings=smass.settings_r16
"""
from __future__ import annotations

import datetime as dt

from django.test import Client, TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_facilities.models import (
    BOOKING_APPROVED,
    BOOKING_CHECKED_IN,
    BOOKING_PENDING,
    BOOKING_REJECTED,
    BOOKING_RELEASED,
    Building,
    Room,
    RoomBooking,
)

PASSWORD = 'R16Ui#2026'
LOGIN = '/r16/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


def fmt(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


class BookingUiTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(code='B1', name='主楼')
        self.room = Room.objects.create(
            code='R101', name='研讨室', building=self.building,
            capacity=20, requires_approval=True)
        self.auto_room = Room.objects.create(
            code='R102', name='自习室', building=self.building,
            capacity=40, requires_approval=False)

        self.student = make_account('R16S1', [RoleCode.STUDENT])
        self.student2 = make_account('R16S2', [RoleCode.STUDENT])
        self.admin = make_account('R16ADM', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')

        tomorrow = timezone.localdate() + dt.timedelta(days=1)
        self.start = timezone.make_aware(datetime_combine(tomorrow, dt.time(9, 0)))
        self.end = timezone.make_aware(datetime_combine(tomorrow, dt.time(10, 0)))
        self.day = tomorrow.isoformat()

    # ---- 页面 ----
    def test_requires_login(self):
        response = self.client.get('/r16/rooms/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_room_list_and_filter(self):
        login(self.client, 'R16S1')
        response = self.client.get('/r16/rooms/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'R101')

        response = self.client.get('/r16/rooms/', {'min_capacity': '100'})
        self.assertNotContains(response, 'R101')

        response = self.client.get('/r16/rooms/', {'room_type': 'lab'})
        self.assertNotContains(response, 'R101')

    def test_room_detail_shows_calendar(self):
        login(self.client, 'R16S1')
        response = self.client.get('/r16/rooms/{}/'.format(self.room.pk),
                                   {'date': self.day})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '预约申请')
        self.assertContains(response, '当日日历')

    # ---- 预约 ----
    def test_create_booking_pending(self):
        login(self.client, 'R16S1')
        response = self.client.post(
            '/r16/rooms/{}/book/'.format(self.room.pk),
            {'date': self.day, 'start_at': fmt(self.start),
             'end_at': fmt(self.end), 'purpose': '项目组会', 'attendees': '8'})
        self.assertEqual(302, response.status_code)
        booking = RoomBooking.objects.get(room=self.room, account=self.student)
        self.assertEqual(BOOKING_PENDING, booking.status)

    def test_auto_approved_room(self):
        login(self.client, 'R16S1')
        response = self.client.post(
            '/r16/rooms/{}/book/'.format(self.auto_room.pk),
            {'date': self.day, 'start_at': fmt(self.start),
             'end_at': fmt(self.end), 'purpose': '自习', 'attendees': '1'})
        self.assertEqual(302, response.status_code)
        booking = RoomBooking.objects.get(room=self.auto_room)
        self.assertEqual(BOOKING_APPROVED, booking.status)

    def test_conflict_is_visible(self):
        login(self.client, 'R16S1')
        payload = {'date': self.day, 'start_at': fmt(self.start),
                   'end_at': fmt(self.end), 'purpose': '第一场', 'attendees': '2'}
        self.client.post('/r16/rooms/{}/book/'.format(self.room.pk), payload)

        payload['purpose'] = '第二场'
        response = self.client.post(
            '/r16/rooms/{}/book/'.format(self.room.pk), payload)
        self.assertEqual(400, response.status_code)
        self.assertContains(response, '已被占用', status_code=400)

    def test_capacity_rejected(self):
        login(self.client, 'R16S1')
        response = self.client.post(
            '/r16/rooms/{}/book/'.format(self.room.pk),
            {'date': self.day, 'start_at': fmt(self.start),
             'end_at': fmt(self.end), 'purpose': '超员', 'attendees': '99'})
        self.assertEqual(400, response.status_code)
        self.assertContains(response, '超过房间容量', status_code=400)

    # ---- 审批 ----
    def _student_booking(self, purpose='待审批'):
        return RoomBooking.objects.create(
            room=self.room, account=self.student, purpose=purpose,
            start_at=self.start, end_at=self.end, attendees=5,
            status=BOOKING_PENDING)

    def test_admin_approves(self):
        booking = self._student_booking()
        login(self.client, 'R16ADM')
        response = self.client.post(
            '/r16/approvals/{}/approve/'.format(booking.pk))
        self.assertEqual(302, response.status_code)
        booking.refresh_from_db()
        self.assertEqual(BOOKING_APPROVED, booking.status)

    def test_self_approval_denied(self):
        booking = RoomBooking.objects.create(
            room=self.room, account=self.admin, purpose='本人申请',
            start_at=self.start, end_at=self.end, status=BOOKING_PENDING)
        login(self.client, 'R16ADM')
        response = self.client.post(
            '/r16/approvals/{}/approve/'.format(booking.pk))
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])
        booking.refresh_from_db()
        self.assertEqual(BOOKING_PENDING, booking.status)

    def test_reject_requires_reason(self):
        booking = self._student_booking('驳回测试')
        login(self.client, 'R16ADM')
        response = self.client.post(
            '/r16/approvals/{}/reject/'.format(booking.pk), {'reason': ''})
        self.assertIn('error=', response['Location'])
        booking.refresh_from_db()
        self.assertEqual(BOOKING_PENDING, booking.status)

        response = self.client.post(
            '/r16/approvals/{}/reject/'.format(booking.pk),
            {'reason': '时段与教学冲突'})
        self.assertIn('ok=', response['Location'])
        booking.refresh_from_db()
        self.assertEqual(BOOKING_REJECTED, booking.status)
        self.assertEqual('时段与教学冲突', booking.cancel_reason)

    def test_approvals_forbidden_for_student(self):
        login(self.client, 'R16S1')
        response = self.client.get('/r16/approvals/')
        self.assertEqual(403, response.status_code)

    # ---- 签到 / 释放 / 越权 ----
    def test_check_in_and_release(self):
        booking = RoomBooking.objects.create(
            room=self.room, account=self.student, purpose='签到流程',
            start_at=self.start, end_at=self.end, status=BOOKING_APPROVED)
        login(self.client, 'R16S1')
        self.client.post('/r16/bookings/{}/checkin/'.format(booking.pk))
        booking.refresh_from_db()
        self.assertEqual(BOOKING_CHECKED_IN, booking.status)

        self.client.post('/r16/bookings/{}/release/'.format(booking.pk))
        booking.refresh_from_db()
        self.assertEqual(BOOKING_RELEASED, booking.status)

    def test_other_student_cannot_cancel(self):
        booking = RoomBooking.objects.create(
            room=self.room, account=self.student, purpose='他人预约',
            start_at=self.start, end_at=self.end, status=BOOKING_APPROVED)
        login(self.client, 'R16S2')
        response = self.client.post(
            '/r16/bookings/{}/cancel/'.format(booking.pk), {'reason': '抢占'})
        self.assertIn('error=', response['Location'])
        booking.refresh_from_db()
        self.assertEqual(BOOKING_APPROVED, booking.status)

    def test_calendar_lists_booking(self):
        RoomBooking.objects.create(
            room=self.room, account=self.student, purpose='日历可见',
            start_at=self.start, end_at=self.end, status=BOOKING_APPROVED)
        login(self.client, 'R16S1')
        response = self.client.get('/r16/calendar/', {'date': self.day})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '日历可见')

    def test_bookings_page_scoped(self):
        RoomBooking.objects.create(
            room=self.room, account=self.student, purpose='我的预约A',
            start_at=self.start, end_at=self.end, status=BOOKING_APPROVED)
        RoomBooking.objects.create(
            room=self.room, account=self.student2, purpose='他人预约B',
            start_at=self.start + dt.timedelta(hours=3),
            end_at=self.end + dt.timedelta(hours=3),
            status=BOOKING_APPROVED)
        login(self.client, 'R16S1')
        response = self.client.get('/r16/bookings/')
        self.assertContains(response, '我的预约A')
        self.assertNotContains(response, '他人预约B')


def datetime_combine(day, clock):
    return dt.datetime.combine(day, clock)
