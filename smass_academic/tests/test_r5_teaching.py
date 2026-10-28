"""R5-04/05/06：任课、修读与端到端流程。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services
from smass_academic.models import (
    Enrollment,
    EnrollmentHistory,
    TeachingAssignment,
    TeachingSection,
)

PASSWORD = 'R5Teach#2024'


def make_account(login, role, person_type='teacher'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r5_teaching')
    return Account.objects.get(pk=account.pk)


class TeachingFixture(TestCase):
    def setUp(self):
        self.year = services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))
        self.term = services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15))
        self.course = services.create_course('CS101', '程序设计')
        self.section = services.create_section(self.term, self.course, 'A', capacity=2)
        self.section2 = services.create_section(self.term, self.course, 'B')

        self.teacher = make_account('T501', RoleCode.TEACHER)
        self.teacher2 = make_account('T502', RoleCode.TEACHER)
        self.student = make_account('S501', RoleCode.STUDENT, 'student')
        self.student2 = make_account('S502', RoleCode.STUDENT, 'student')


class AssignmentTests(TeachingFixture):
    def test_assign_teacher(self):
        assignment = services.assign_teacher(self.section, self.teacher, assigned_by='admin')
        self.assertIsNone(assignment.revoked_at)
        self.assertTrue(services.can_teach(self.teacher, self.section))

    def test_teacher_cannot_teach_unassigned_section(self):
        services.assign_teacher(self.section, self.teacher)
        self.assertFalse(services.can_teach(self.teacher, self.section2))

    def test_teacher_sections_only_own(self):
        services.assign_teacher(self.section, self.teacher)

        own = set(services.teacher_sections(self.teacher).values_list('pk', flat=True))
        self.assertEqual(own, {self.section.pk})
        self.assertEqual(services.teacher_sections(self.teacher2).count(), 0)

    def test_duplicate_assignment_rejected(self):
        services.assign_teacher(self.section, self.teacher)
        with self.assertRaises(services.DuplicateError):
            services.assign_teacher(self.section, self.teacher)

    def test_revoked_assignment_loses_access(self):
        assignment = services.assign_teacher(self.section, self.teacher)
        self.assertTrue(services.can_teach(self.teacher, self.section))

        services.revoke_assignment(assignment)

        self.assertFalse(services.can_teach(self.teacher, self.section))
        self.assertEqual(services.teacher_sections(self.teacher).count(), 0)

    def test_inactive_teacher_cannot_be_assigned(self):
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])
        with self.assertRaises(services.AccessError):
            services.assign_teacher(self.section, self.teacher)

    def test_roster_denied_for_other_teacher(self):
        services.assign_teacher(self.section, self.teacher)
        with self.assertRaises(services.AccessError):
            services.section_roster(self.section, self.teacher2)

    def test_roster_allowed_for_assigned_teacher(self):
        services.assign_teacher(self.section, self.teacher)
        roster = services.section_roster(self.section, self.teacher)
        self.assertEqual(roster.count(), 0)  # 还没人选


class EnrollmentTests(TeachingFixture):
    def test_enroll(self):
        enrollment = services.enroll(self.section, self.student, actor='self')
        self.assertEqual(enrollment.status, 'enrolled')
        self.assertEqual(EnrollmentHistory.objects.filter(enrollment=enrollment).count(), 1)

    def test_duplicate_enrollment_rejected(self):
        services.enroll(self.section, self.student)
        with self.assertRaises(services.DuplicateError):
            services.enroll(self.section, self.student)

    def test_capacity_enforced(self):
        services.enroll(self.section, self.student)
        services.enroll(self.section, self.student2)

        third = make_account('S503', RoleCode.STUDENT, 'student')
        with self.assertRaises(services.CapacityError):
            services.enroll(self.section, third)

    def test_unlimited_capacity(self):
        for index in range(5):
            account = make_account('SU{:03d}'.format(index), RoleCode.STUDENT, 'student')
            services.enroll(self.section2, account)

        self.assertEqual(
            Enrollment.objects.filter(section=self.section2, status='enrolled').count(), 5
        )

    def test_drop_and_history(self):
        enrollment = services.enroll(self.section, self.student)
        services.drop(enrollment, actor='self')

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, 'dropped')
        self.assertEqual(
            EnrollmentHistory.objects.filter(enrollment=enrollment).count(), 2
        )

    def test_drop_twice_rejected(self):
        enrollment = services.enroll(self.section, self.student)
        services.drop(enrollment)
        with self.assertRaises(services.DuplicateError):
            services.drop(enrollment)

    def test_reenroll_after_drop(self):
        enrollment = services.enroll(self.section, self.student)
        services.drop(enrollment)
        again = services.enroll(self.section, self.student, actor='self')

        self.assertEqual(again.pk, enrollment.pk)
        self.assertEqual(again.status, 'enrolled')
        self.assertEqual(
            EnrollmentHistory.objects.filter(enrollment=again).count(), 3
        )

    def test_closed_section_rejects_enrollment(self):
        self.section.status = 'closed'
        self.section.save(update_fields=['status'])
        with self.assertRaises(services.AcademicError):
            services.enroll(self.section, self.student)

    def test_student_sections_only_own(self):
        services.enroll(self.section, self.student)
        services.enroll(self.section2, self.student2)

        mine = set(services.student_sections(self.student).values_list('pk', flat=True))
        self.assertEqual(mine, {self.section.pk})
        self.assertEqual(services.student_sections(self.student2).count(), 1)


class TeachingViewTests(TeachingFixture):
    def test_teacher_workspace_shows_only_assigned(self):
        services.assign_teacher(self.section, self.teacher)
        self.client.force_login(self.teacher)

        resp = self.client.get('/r5/workspace/',
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        codes = {row['code'] for row in resp.json()['sections']}
        self.assertEqual(codes, {'A'})

    def test_roster_endpoint_denied_for_other_teacher(self):
        services.assign_teacher(self.section, self.teacher)
        self.client.force_login(self.teacher2)

        resp = self.client.get('/r5/sections/{}/roster/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 403)

    def test_roster_endpoint_ok_for_assigned(self):
        services.assign_teacher(self.section, self.teacher)
        services.enroll(self.section, self.student)
        self.client.force_login(self.teacher)

        resp = self.client.get('/r5/sections/{}/roster/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['rows']), 1)

    def test_student_my_sections(self):
        services.enroll(self.section, self.student)
        self.client.force_login(self.student)

        resp = self.client.get('/r5/my-courses/',
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        codes = {row['code'] for row in resp.json()['sections']}
        self.assertEqual(codes, {'A'})


class EndToEndFlowTests(TeachingFixture):
    """R5-06：学期→课程→教学班→教师→学生→三端可见性。"""

    def test_full_flow(self):
        # 1) 教师被分配到 A 班
        services.assign_teacher(self.section, self.teacher, assigned_by='admin')

        # 2) 学生选 A 班
        services.enroll(self.section, self.student, actor='self')

        # 3) 教师看到 A 班与名册
        self.assertTrue(services.can_teach(self.teacher, self.section))
        roster = services.section_roster(self.section, self.teacher)
        self.assertEqual(roster.count(), 1)
        self.assertEqual(roster.first().account, self.student)

        # 4) 学生看到自己选课
        self.assertEqual(
            list(services.student_sections(self.student).values_list('pk', flat=True)),
            [self.section.pk],
        )

        # 5) 未授权教师看不到
        self.assertFalse(services.can_teach(self.teacher2, self.section))

        # 6) 撤销任课后教师立即失去访问
        assignment = TeachingAssignment.objects.get(section=self.section, account=self.teacher)
        services.revoke_assignment(assignment)
        self.assertFalse(services.can_teach(self.teacher, self.section))
        with self.assertRaises(services.AccessError):
            services.section_roster(self.section, self.teacher)
