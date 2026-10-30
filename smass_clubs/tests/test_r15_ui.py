"""R15 页面层：组织创建、成员申请审批与干部任命的真实页面流程。

运行::

    python manage.py test smass_clubs.tests.test_r15_ui --settings=smass.settings_r15
"""
from __future__ import annotations

from django.test import Client, TestCase

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

PASSWORD = 'R15Ui#2026'
LOGIN = '/r21/login/'


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


class ClubUiTests(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.admin = make_account('r15uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.leader_acc = make_account('r15uileader', [RoleCode.STUDENT])
        self.student = make_account('r15uistu', [RoleCode.STUDENT])

        self.leader_record = StudentRecord.objects.create(
            student_no='S8201', name='负责人', unit=self.klass, account=self.leader_acc)
        self.me = StudentRecord.objects.create(
            student_no='S8202', name='成员', unit=self.klass, account=self.student)

        self.club = Club.objects.create(
            code='CLUB-UI', name='界面社团', category='club', status='active',
            created_by=str(self.admin.pk))
        ClubMembership.objects.create(
            club=self.club, record=self.leader_record, role='leader', status='active')

    def test_requires_login(self):
        response = self.client.get('/r15/clubs/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_cannot_create_club(self):
        login(self.client, 'r15uistu')
        response = self.client.post('/r15/clubs/create/', {
            'code': 'CLUB-X', 'name': '非法', 'category': 'club',
        })
        self.assertEqual(403, response.status_code)

    def test_admin_creates_club_via_page(self):
        admin = Client()
        login(admin, 'r15uiadmin')
        response = admin.post('/r15/clubs/create/', {
            'code': 'CLUB-NEW', 'name': '新建社团', 'category': 'association',
        })
        self.assertEqual(302, response.status_code)
        self.assertTrue(Club.objects.filter(code='CLUB-NEW').exists())

    def test_student_applies_via_page(self):
        login(self.client, 'r15uistu')
        response = self.client.post('/r15/clubs/{}/apply/'.format(self.club.pk))
        self.assertEqual(302, response.status_code)
        self.assertEqual(ClubMembership.objects.get(
            club=self.club, record=self.me).status, 'pending')

    def test_leader_approves_via_page(self):
        membership = ClubMembership.objects.create(
            club=self.club, record=self.me, role='member', status='pending')
        leader = Client()
        login(leader, 'r15uileader')
        response = leader.post('/r15/memberships/{}/approve/'.format(membership.pk))
        self.assertEqual(302, response.status_code)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'active')

    def test_leader_appoints_post_via_page(self):
        membership = ClubMembership.objects.create(
            club=self.club, record=self.me, role='member', status='active')
        leader = Client()
        login(leader, 'r15uileader')
        response = leader.post('/r15/clubs/{}/appoint/'.format(self.club.pk), {
            'record': self.me.pk, 'title': 'president', 'term': '2026-2027',
        })
        self.assertEqual(302, response.status_code)
        post = ClubPost.objects.get(club=self.club, record=self.me)
        self.assertEqual(post.title, 'president')
        self.assertEqual(post.status, 'active')

    def test_student_sees_only_own_membership(self):
        ClubMembership.objects.create(
            club=self.club, record=self.me, role='member', status='active')
        login(self.client, 'r15uistu')
        response = self.client.get('/r15/clubs/{}/'.format(self.club.pk))
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'S8202')
        self.assertNotContains(response, 'S8201')

    def test_posts_page_lists_own_posts(self):
        ClubMembership.objects.create(
            club=self.club, record=self.me, role='member', status='active')
        ClubPost.objects.create(
            club=self.club, record=self.me, title='minister', term='2026-2027',
            status='active')
        login(self.client, 'r15uistu')
        response = self.client.get('/r15/posts/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'S8202')
