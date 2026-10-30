"""R15 服务层：组织、成员申请审批与干部任职。

运行::

    python manage.py test smass_clubs.tests.test_r15_services --settings=smass.settings_r15
"""
from __future__ import annotations

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_clubs import services
from smass_clubs.models import Club, ClubMembership, ClubPost

PASSWORD = 'R15Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ClubBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('r15teacher', [RoleCode.TEACHER], person_type='teacher')
        self.admin = make_account('r15admin', [RoleCode.SYSTEM_ADMIN], person_type='admin')
        self.leader = make_account('r15leader', [RoleCode.STUDENT])
        self.student = make_account('r15stu', [RoleCode.STUDENT])
        self.student2 = make_account('r15stu2', [RoleCode.STUDENT])

        self.leader_record = StudentRecord.objects.create(
            student_no='S8101', name='负责人', unit=self.klass, account=self.leader)
        self.me = StudentRecord.objects.create(
            student_no='S8102', name='成员', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S8103', name='其他', unit=self.klass, account=self.student2)

        self.club = services.create_club(
            self.admin, 'CLUB-ROBOT', '机器人社团', 'club')
        # 负责人：先申请再批准，然后提升
        membership = services.apply_join(self.club, self.leader_record, self.leader)
        services.approve_join(membership, self.admin)
        services.promote_leader(membership, self.admin)


class ClubTests(ClubBase):
    def test_create_club(self):
        self.assertEqual(self.club.code, 'CLUB-ROBOT')
        self.assertEqual(self.club.status, 'active')

    def test_student_cannot_create(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_club(self.student, 'X', '非法', 'club')

    def test_duplicate_code(self):
        with self.assertRaises(services.ClubError) as ctx:
            services.create_club(self.admin, 'CLUB-ROBOT', '重复', 'club')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_CODE')

    def test_bad_category(self):
        with self.assertRaises(services.ClubError) as ctx:
            services.create_club(self.admin, 'CLUB-X', 'X', 'unknown')
        self.assertEqual(ctx.exception.code, 'BAD_CATEGORY')

    def test_archive_blocks_join(self):
        services.archive_club(self.club, self.admin)
        self.club.refresh_from_db()
        with self.assertRaises(services.ClubError) as ctx:
            services.apply_join(self.club, self.me, self.student)
        self.assertEqual(ctx.exception.code, 'CLUB_ARCHIVED')


class MembershipTests(ClubBase):
    def test_apply_and_approve(self):
        membership = services.apply_join(self.club, self.me, self.student)
        self.assertEqual(membership.status, 'pending')
        services.approve_join(membership, self.leader)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'active')
        self.assertIsNotNone(membership.joined_at)

    def test_duplicate_application(self):
        services.apply_join(self.club, self.me, self.student)
        with self.assertRaises(services.ClubError) as ctx:
            services.apply_join(self.club, self.me, self.student)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_MEMBERSHIP')

    def test_reject_requires_reason(self):
        membership = services.apply_join(self.club, self.me, self.student)
        with self.assertRaises(services.ClubError) as ctx:
            services.reject_join(membership, self.leader, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_leave_and_rejoin(self):
        membership = services.apply_join(self.club, self.me, self.student)
        services.approve_join(membership, self.leader)
        services.leave_club(membership, self.student)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'left')

        again = services.apply_join(self.club, self.me, self.student)
        self.assertEqual(again.pk, membership.pk)
        self.assertEqual(again.status, 'pending')

    def test_promote_and_demote(self):
        membership = services.apply_join(self.club, self.me, self.student)
        services.approve_join(membership, self.leader)
        services.promote_leader(membership, self.leader)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'leader')
        services.demote_leader(membership, self.leader)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'member')

    def test_non_leader_cannot_approve(self):
        membership = services.apply_join(self.club, self.me, self.student)
        with self.assertRaises(services.PermissionDenied):
            services.approve_join(membership, self.student2)


class PostTests(ClubBase):
    def _member(self):
        membership = services.apply_join(self.club, self.me, self.student)
        services.approve_join(membership, self.admin)
        return membership

    def test_appoint_and_end(self):
        self._member()
        post = services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        self.assertEqual(post.status, 'active')
        services.end_post(post, self.leader)
        post.refresh_from_db()
        self.assertEqual(post.status, 'ended')

    def test_non_member_cannot_be_appointed(self):
        with self.assertRaises(services.ClubError) as ctx:
            services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        self.assertEqual(ctx.exception.code, 'NOT_MEMBER')

    def test_duplicate_post_taken(self):
        self._member()
        services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        with self.assertRaises(services.ClubError) as ctx:
            services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        self.assertEqual(ctx.exception.code, 'POST_TAKEN')

    def test_unique_posts_conflict(self):
        self._member()
        services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        with self.assertRaises(services.ClubError) as ctx:
            services.appoint_post(self.club, self.me, 'vice_president', '2026-2027', self.leader)
        self.assertEqual(ctx.exception.code, 'POST_TAKEN')

    def test_minister_allows_multiple(self):
        self._member()
        other_membership = services.apply_join(self.club, self.other, self.student2)
        services.approve_join(other_membership, self.admin)
        services.appoint_post(self.club, self.me, 'minister', '2026-2027', self.leader)
        second = services.appoint_post(self.club, self.other, 'minister', '2026-2027', self.leader)
        self.assertEqual(second.status, 'active')

    def test_end_post_frees_slot(self):
        self._member()
        post = services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        services.end_post(post, self.leader)
        again = services.appoint_post(self.club, self.me, 'president', '2026-2027', self.leader)
        self.assertEqual(again.status, 'active')


class ScopingTests(ClubBase):
    def test_student_sees_only_own_memberships(self):
        services.apply_join(self.club, self.me, self.student)
        self.assertEqual(services.scoped_memberships(self.student).count(), 1)
        self.assertEqual(services.scoped_memberships(self.student2).count(), 0)
        self.assertEqual(
            services.scoped_memberships(self.admin).count(), 2)

    def test_student_sees_only_own_posts(self):
        self.assertEqual(services.scoped_posts(self.student).count(), 0)
