"""R5-01/02/03：学年、学期、课程、教学班。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services
from smass_academic.models import AcademicTerm, AcademicYear, Course, TeachingSection

PASSWORD = 'R5Pass#2024'


def make_account(login, role):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin'
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:  # role=None 表示"无角色账号"，不能授予 None
        core_services.grant_role(account, role, granted_by='r5_test')
    return Account.objects.get(pk=account.pk)


class AcademicYearTests(TestCase):
    def test_create_year(self):
        year = services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))
        self.assertEqual(year.code, '2025-2026')
        self.assertFalse(year.is_active)

    def test_invalid_range_rejected(self):
        with self.assertRaises(services.DateRangeError):
            services.create_year('X', date(2026, 9, 1), date(2025, 9, 1))

    def test_duplicate_code_rejected(self):
        services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))
        with self.assertRaises(services.DuplicateError):
            services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))

    def test_only_one_active_year(self):
        a = services.create_year('Y1', date(2025, 1, 1), date(2025, 12, 31), is_active=True)
        b = services.create_year('Y2', date(2026, 1, 1), date(2026, 12, 31), is_active=True)

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)
        self.assertEqual(AcademicYear.objects.filter(is_active=True).count(), 1)

    def test_activate_moves_flag(self):
        a = services.create_year('Y1', date(2025, 1, 1), date(2025, 12, 31))
        b = services.create_year('Y2', date(2026, 1, 1), date(2026, 12, 31))
        services.activate_year(a)
        services.activate_year(b)

        a.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)


class AcademicTermTests(TestCase):
    def setUp(self):
        self.year = services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))

    def test_create_term_within_year(self):
        term = services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15))
        self.assertEqual(term.semester, '1')

    def test_term_outside_year_rejected(self):
        with self.assertRaises(services.DateRangeError):
            services.create_term(self.year, '1', date(2025, 1, 1), date(2025, 6, 1))

    def test_term_invalid_range_rejected(self):
        with self.assertRaises(services.DateRangeError):
            services.create_term(self.year, '1', date(2025, 12, 1), date(2025, 10, 1))

    def test_duplicate_semester_in_year_rejected(self):
        services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15))
        with self.assertRaises(services.DuplicateError):
            services.create_term(self.year, '1', date(2026, 2, 1), date(2026, 6, 30))

    def test_only_one_active_term(self):
        t1 = services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15),
                                  is_active=True)
        t2 = services.create_term(self.year, '2', date(2026, 2, 1), date(2026, 6, 30),
                                  is_active=True)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertFalse(t1.is_active)
        self.assertTrue(t2.is_active)

    def test_current_term(self):
        term = services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15),
                                    is_active=True)
        self.assertEqual(services.current_term(), term)


class CourseTests(TestCase):
    def test_create_course(self):
        course = services.create_course('CS101', '程序设计', credit=3)
        self.assertEqual(course.code, 'CS101')
        self.assertFalse(course.is_active is False)

    def test_duplicate_code_rejected(self):
        services.create_course('CS101', '程序设计')
        with self.assertRaises(services.DuplicateError):
            services.create_course('CS101', '另一门')

    def test_empty_fields_rejected(self):
        with self.assertRaises(services.AcademicError):
            services.create_course('', '名称')
        with self.assertRaises(services.AcademicError):
            services.create_course('X', '')

    def test_negative_credit_rejected(self):
        with self.assertRaises(services.AcademicError):
            services.create_course('X', 'Y', credit=-1)

    def test_search_by_keyword(self):
        services.create_course('CS101', '程序设计')
        services.create_course('MA201', '高等数学')

        self.assertEqual(services.search_courses('CS').count(), 1)
        self.assertEqual(services.search_courses('数学').count(), 1)


class SectionTests(TestCase):
    def setUp(self):
        self.year = services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))
        self.term = services.create_term(self.year, '1', date(2025, 9, 1), date(2026, 1, 15))
        self.course = services.create_course('CS101', '程序设计')

    def test_create_section(self):
        section = services.create_section(self.term, self.course, 'A', capacity=30)
        self.assertEqual(section.code, 'A')
        self.assertEqual(section.status, 'open')

    def test_duplicate_section_code_rejected(self):
        services.create_section(self.term, self.course, 'A')
        with self.assertRaises(services.DuplicateError):
            services.create_section(self.term, self.course, 'A')

    def test_inactive_course_cannot_open(self):
        self.course.is_active = False
        self.course.save(update_fields=['is_active'])
        with self.assertRaises(services.AcademicError):
            services.create_section(self.term, self.course, 'B')

    def test_negative_capacity_rejected(self):
        with self.assertRaises(services.AcademicError):
            services.create_section(self.term, self.course, 'C', capacity=-1)


class AcademicViewTests(TestCase):
    def setUp(self):
        self.admin = make_account('R5ADM', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('R5TCH', RoleCode.TEACHER)
        self.nobody = make_account('R5NOB', None)
        self.year = services.create_year('2025-2026', date(2025, 9, 1), date(2026, 8, 31))

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/r5/years/').status_code, 403)

    def test_no_role_denied(self):
        self.client.force_login(self.nobody)
        self.assertEqual(self.client.get('/r5/years/').status_code, 403)

    def test_admin_sees_year_page(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/r5/years/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('2025-2026', resp.content.decode('utf-8'))

    def test_create_year_api(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r5/years/create/',
            data='{"code":"2026-2027","start_date":"2026-09-01","end_date":"2027-08-31"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AcademicYear.objects.filter(code='2026-2027').exists())

    def test_create_term_outside_year_returns_400(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            '/r5/terms/create/',
            data='{"year":%d,"semester":"1","start_date":"2024-01-01","end_date":"2024-06-01"}'
                 % self.year.pk,
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('code'), 'DATE_RANGE')

    def test_health(self):
        resp = self.client.get('/r5/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
