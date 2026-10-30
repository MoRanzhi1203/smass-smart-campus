"""R15 真实浏览器 E2E（Playwright + Chromium）。

覆盖：管理员创建组织 → 学生申请加入 → 负责人在页面上批准 →
负责人任命干部 → 学生任职页可见。

Playwright/Chromium 不可用时用例 SkipTest，不伪装通过。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_clubs.models import Club, ClubMembership, ClubPost

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'R15Browser#2026'


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
class R15BrowserFlowTests(StaticLiveServerTestCase):
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
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('R15E2EA', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.leader_acc = make_account('R15E2EL', [RoleCode.STUDENT])
        self.student = make_account('R15E2ES', [RoleCode.STUDENT])
        self.leader_record = StudentRecord.objects.create(
            student_no='S8301', name='负责人', unit=self.klass, account=self.leader_acc)
        self.me = StudentRecord.objects.create(
            student_no='S8302', name='成员', unit=self.klass, account=self.student)

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
        page.goto(self.live_server_url + '/r15/login/')
        page.fill('input[name=login_name]', login_name)
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _new_page(self, login_name):
        context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(15000)
        self._login(page, login_name)
        return context, page

    def test_club_join_approve_and_appoint(self):
        context, admin = self._new_page('R15E2EA')
        try:
            admin.goto(self.live_server_url + '/r15/clubs/')
            admin.fill('input[name=code]', 'CLUB-E2E')
            admin.fill('input[name=name]', '浏览器社团')
            admin.select_option('select[name=category]', 'club')
            admin.click('form[action="/r15/clubs/create/"] button[type=submit]')
            self.assertIn('组织已创建', admin.content())
        finally:
            context.close()

        club = Club.objects.get(code='CLUB-E2E')
        ClubMembership.objects.create(
            club=club, record=self.leader_record, role='leader', status='active')

        self._login(self.page, 'R15E2ES')
        self.page.goto('{}/r15/clubs/{}/'.format(self.live_server_url, club.pk))
        self.page.click('form[action$="/apply/"] button[type=submit]')
        self.assertIn('申请已提交', self.page.content())

        membership = ClubMembership.objects.get(club=club, record=self.me)
        context, leader = self._new_page('R15E2EL')
        try:
            leader.goto('{}/r15/clubs/{}/'.format(self.live_server_url, club.pk))
            leader.click('form[action="/r15/memberships/{}/approve/"] button'.format(
                membership.pk))
            self.assertIn('操作成功', leader.content())

            leader.goto('{}/r15/clubs/{}/'.format(self.live_server_url, club.pk))
            leader.select_option('select[name=record]', str(self.me.pk))
            leader.fill('input[name=term]', '2026-2027')
            leader.click('form[action="/r15/clubs/{}/appoint/"] button[type=submit]'.format(
                club.pk))
            self.assertIn('任命成功', leader.content())
        finally:
            context.close()

        post = ClubPost.objects.get(club=club, record=self.me)
        self.assertEqual(post.status, 'active')
        self.page.goto(self.live_server_url + '/r15/posts/')
        self.assertIn('主席/会长', self.page.content())
        self.assertIn('S8302', self.page.content())
