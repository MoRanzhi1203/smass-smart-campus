"""U4：R5 教学垂直切片（三角色 E2E）。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services
from smass_academic.models import (
    AcademicTerm,
    AcademicYear,
    Course,
    Enrollment,
    TeachingAssignment,
    TeachingSection,
)

PASSWORD = 'U4Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u4')
    return Account.objects.get(pk=account.pk)


class U4Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = make_account('U4ADM', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('U4T', RoleCode.TEACHER, 'teacher')
        self.teacher2 = make_account('U4T2', RoleCode.TEACHER, 'teacher')
        self.student = make_account('U4S', RoleCode.STUDENT, 'student')
        self.student2 = make_account('U4S2', RoleCode.STUDENT, 'student')

        self.year = AcademicYear.objects.create(
            code='U4-Y', start_date=date(2025, 9, 1), end_date=date(2026, 8, 31))
        self.term = AcademicTerm.objects.create(
            year=self.year, semester='1',
            start_date=date(2025, 9, 1), end_date=date(2026, 1, 15))
        self.course = Course.objects.create(code='U4-C1', title='U4课程', credit=3)
        self.section = TeachingSection.objects.create(
            term=self.term, course=self.course, code='A', capacity=2)

        self.client.force_login(self.admin)


class YearTermCourseFormTests(U4Fixture):
    def test_year_new_page(self):
        resp = self.client.get('/r5/years/new/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="year-form"', resp.content.decode('utf-8'))

    def test_create_year_persists(self):
        resp = self.client.post('/r5/years/new/', {
            'code': 'U4-NEW', 'start_date': '2027-09-01', 'end_date': '2028-08-31',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AcademicYear.objects.filter(code='U4-NEW').exists())

    def test_year_invalid_range_rejected(self):
        resp = self.client.post('/r5/years/new/', {
            'code': 'U4-BAD', 'start_date': '2028-09-01', 'end_date': '2027-08-31',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="form-error"', resp.content.decode('utf-8'))
        self.assertFalse(AcademicYear.objects.filter(code='U4-BAD').exists())

    def test_year_bad_date_format(self):
        resp = self.client.post('/r5/years/new/', {
            'code': 'U4-FMT', 'start_date': 'oops', 'end_date': '2028-08-31',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'YYYY-MM-DD')

    def test_term_outside_year_rejected(self):
        resp = self.client.post('/r5/terms/new/', {
            'year': self.year.pk, 'semester': '2',
            'start_date': '2024-01-01', 'end_date': '2024-06-01',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')
        self.assertEqual(
            AcademicTerm.objects.filter(year=self.year, semester='2').count(), 0)

    def test_create_term_persists(self):
        resp = self.client.post('/r5/terms/new/', {
            'year': self.year.pk, 'semester': '2',
            'start_date': '2026-02-01', 'end_date': '2026-06-30',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            AcademicTerm.objects.filter(year=self.year, semester='2').exists())

    def test_create_course_persists(self):
        resp = self.client.post('/r5/courses/new/', {
            'code': 'U4-C9', 'title': '新课程', 'credit': '2.5',
            'course_type': '选修', 'is_active': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Course.objects.filter(code='U4-C9').exists())

    def test_course_duplicate_rejected(self):
        resp = self.client.post('/r5/courses/new/', {
            'code': 'U4-C1', 'title': '重复', 'credit': '', 'is_active': '1',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')

    def test_create_section_persists(self):
        resp = self.client.post('/r5/sections/new/', {
            'term': self.term.pk, 'course': self.course.pk,
            'code': 'B', 'capacity': '20',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeachingSection.objects.filter(
            term=self.term, course=self.course, code='B').exists())

    def test_section_duplicate_code_rejected(self):
        resp = self.client.post('/r5/sections/new/', {
            'term': self.term.pk, 'course': self.course.pk,
            'code': 'A', 'capacity': '10',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')

    def test_teacher_cannot_create_year(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get('/r5/years/new/').status_code, 403)


class AssignmentTests(U4Fixture):
    def test_assign_teacher(self):
        resp = self.client.post('/r5/sections/{}/assign/'.format(self.section.pk), {
            'teacher': self.teacher.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(TeachingAssignment.objects.filter(
            section=self.section, account=self.teacher, revoked_at__isnull=True).exists())

    def test_duplicate_assign_rejected(self):
        services.assign_teacher(self.section, self.teacher)
        resp = self.client.post('/r5/sections/{}/assign/'.format(self.section.pk), {
            'teacher': self.teacher.pk,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="form-error"')

    def test_revoke_assignment(self):
        assignment = services.assign_teacher(self.section, self.teacher)
        resp = self.client.post('/r5/assignments/{}/revoke/'.format(assignment.pk))
        self.assertEqual(resp.status_code, 302)

        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.revoked_at)
        self.assertFalse(services.can_teach(self.teacher, self.section))

    def test_assign_page_lists_assignments(self):
        services.assign_teacher(self.section, self.teacher)
        resp = self.client.get('/r5/sections/{}/assign/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="assignment-table"', resp.content.decode('utf-8'))


class RosterTests(U4Fixture):
    def test_assigned_teacher_sees_roster(self):
        services.assign_teacher(self.section, self.teacher)
        services.enroll(self.section, self.student)
        self.client.force_login(self.teacher)

        resp = self.client.get('/r5/sections/{}/roster/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="roster-table"', body)
        self.assertIn('U4S', body)

    def test_other_teacher_denied(self):
        services.assign_teacher(self.section, self.teacher)
        self.client.force_login(self.teacher2)
        self.assertEqual(
            self.client.get('/r5/sections/{}/roster/'.format(self.section.pk)).status_code,
            403)

    def test_admin_sees_any_roster(self):
        resp = self.client.get('/r5/sections/{}/roster/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_drops_student(self):
        services.assign_teacher(self.section, self.teacher)
        enrollment = services.enroll(self.section, self.student)
        self.client.force_login(self.teacher)

        resp = self.client.post('/r5/sections/{}/roster/{}/drop/'.format(
            self.section.pk, enrollment.pk))
        self.assertEqual(resp.status_code, 302)

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.STATUS_DROPPED)


class EnrollmentTests(U4Fixture):
    def test_enroll_page_renders(self):
        self.client.force_login(self.student)
        resp = self.client.get('/r5/enroll/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="open-section-table"', body)
        self.assertIn('id="my-enroll-table"', body)

    def test_student_enrolls(self):
        self.client.force_login(self.student)
        resp = self.client.post('/r5/enroll/{}/'.format(self.section.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Enrollment.objects.filter(
            section=self.section, account=self.student,
            status=Enrollment.STATUS_ENROLLED).exists())

    def test_student_drops(self):
        enrollment = services.enroll(self.section, self.student)
        self.client.force_login(self.student)

        resp = self.client.post('/r5/enrollments/{}/drop/'.format(enrollment.pk))
        self.assertEqual(resp.status_code, 302)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.STATUS_DROPPED)

    def test_capacity_full_rejected_in_ui(self):
        services.enroll(self.section, self.student)
        services.enroll(self.section, self.student2)
        third = make_account('U4S3', RoleCode.STUDENT, 'student')
        self.client.force_login(third)

        resp = self.client.post('/r5/enroll/{}/'.format(self.section.pk), follow=True)
        # 容量满 -> 不创建修读，且有错误提示
        self.assertFalse(Enrollment.objects.filter(
            section=self.section, account=third,
            status=Enrollment.STATUS_ENROLLED).exists())
        self.assertContains(resp, '容量已满')

    def test_duplicate_enroll_warns(self):
        services.enroll(self.section, self.student)
        self.client.force_login(self.student)

        resp = self.client.post('/r5/enroll/{}/'.format(self.section.pk), follow=True)
        self.assertContains(resp, '已经选过')


class ThreeRoleVisibilityTests(U4Fixture):
    """三角色可见性：管理员配置 -> 教师只见任课 -> 学生只见本人。"""

    def test_full_three_role_journey(self):
        # 1) 管理员分配教师 + 另一班不分配
        other = TeachingSection.objects.create(
            term=self.term, course=self.course, code='B', capacity=5)
        services.assign_teacher(self.section, self.teacher)

        # 2) 教师工作台只显示自己班
        self.client.force_login(self.teacher)
        payload = self.client.get(
            '/r5/workspace/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        codes = {row['code'] for row in payload['sections']}
        self.assertEqual(codes, {'A'})

        # 3) 教师访问未任课班名册 -> 403
        self.assertEqual(
            self.client.get('/r5/sections/{}/roster/'.format(other.pk)).status_code,
            403)

        # 4) 学生选课
        self.client.force_login(self.student)
        self.client.post('/r5/enroll/{}/'.format(self.section.pk))

        # 5) 学生我的课程只有一个
        payload = self.client.get(
            '/r5/my-courses/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertEqual(len(payload['sections']), 1)
        self.assertEqual(payload['sections'][0]['code'], 'A')

        # 6) 另一学生看不到
        self.client.force_login(self.student2)
        payload = self.client.get(
            '/r5/my-courses/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
        self.assertEqual(payload['sections'], [])

    def test_anonymous_denied_everywhere(self):
        self.client.logout()
        for url in ('/r5/years/new/', '/r5/enroll/', '/r5/sections/{}/roster/'.format(
                self.section.pk)):
            self.assertIn(self.client.get(url).status_code, (403, 302), url)
