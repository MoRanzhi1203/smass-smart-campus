"""R16-UI 真实浏览器 E2E（Playwright + Chromium）。

覆盖：登录 → 房间列表 → 选择房间 → 提交预约 → 管理员批准 →
学生签到 → 释放房间；以及冲突时的可见错误。

Playwright/Chromium 不可用时用例会 SkipTest，不伪装通过。
"""
import datetime as dt
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_facilities.models import (
    BOOKING_APPROVED,
    BOOKING_RELEASED,
    Building,
    Room,
    RoomBooking,
)

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R16Browser#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R16BrowserFlowTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        try:
            cls.browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('Chromium 启动失败：{}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.building = Building.objects.create(code='B1', name='主楼')
        self.room = Room.objects.create(
            code='R201', name='浏览器研讨室', building=self.building,
            capacity=20, requires_approval=True)
        make_account('R16S1', [RoleCode.STUDENT])
        make_account('R16ADM', [RoleCode.SYSTEM_ADMIN], person_type='admin')

        tomorrow = timezone.localdate() + dt.timedelta(days=1)
        start = timezone.make_aware(dt.datetime.combine(tomorrow, dt.time(9, 0)))
        end = timezone.make_aware(dt.datetime.combine(tomorrow, dt.time(10, 0)))
        self.start_str = timezone.localtime(start).strftime('%Y-%m-%dT%H:%M')
        self.end_str = timezone.localtime(end).strftime('%Y-%m-%dT%H:%M')
        self.day = tomorrow.isoformat()

        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            super().tearDown()

    def _login(self, page, login_name):
        page.goto(self.live_server_url + '/r16/login/')
        page.fill('input[name=login_name]', login_name)
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _book(self, page, purpose):
        page.goto('{}/r16/rooms/{}/'.format(self.live_server_url, self.room.pk))
        page.fill('input[name=purpose]', purpose)
        page.fill('input[name=start_at]', self.start_str)
        page.fill('input[name=end_at]', self.end_str)
        page.click('form[action="/r16/rooms/{}/book/"] button[type=submit]'.format(
            self.room.pk))

    def test_booking_approve_checkin_release(self):
        self._login(self.page, 'R16S1')
        self._book(self.page, '浏览器全流程')
        self.assertIn('预约已提交', self.page.content())

        admin_context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        try:
            admin_page = admin_context.new_page()
            admin_page.set_default_timeout(15000)
            self._login(admin_page, 'R16ADM')
            admin_page.goto(self.live_server_url + '/r16/approvals/')
            booking = RoomBooking.objects.get(purpose='浏览器全流程')
            admin_page.click(
                'form[action="/r16/approvals/{}/approve/"] button'.format(booking.pk))
            self.assertIn('已批准', admin_page.content())
        finally:
            admin_context.close()

        booking = RoomBooking.objects.get(purpose='浏览器全流程')
        self.assertEqual(BOOKING_APPROVED, booking.status)

        self.page.goto(self.live_server_url + '/r16/bookings/')
        self.page.click(
            'form[action="/r16/bookings/{}/checkin/"] button'.format(booking.pk))
        self.assertIn('签到成功', self.page.content())

        self.page.goto(self.live_server_url + '/r16/bookings/')
        self.page.click(
            'form[action="/r16/bookings/{}/release/"] button'.format(booking.pk))
        self.assertIn('已释放房间', self.page.content())

        booking.refresh_from_db()
        self.assertEqual(BOOKING_RELEASED, booking.status)

    def test_conflict_error_visible(self):
        self._login(self.page, 'R16S1')
        self._book(self.page, '第一场')
        self.assertIn('预约已提交', self.page.content())

        self._book(self.page, '第二场')
        self.assertIn('已被占用', self.page.content())
