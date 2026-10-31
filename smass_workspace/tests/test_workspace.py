"""产品层回归测试：三端落地、越权拒绝、对象范围、跨端同步与管理端操作。

运行::

    python manage.py test smass_workspace --settings=smass.settings_product

测试使用独立测试库（``test_smass_product_dev``），不读演示数据，
所有夹具在本文件内构造。
"""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, StudentProfile, TeacherProfile
from smass_academic import services as academic_services
from smass_academic.models import (
    AcademicTerm, AcademicYear, Course, Enrollment, TeachingAssignment,
    TeachingSection,
)
from smass_attendance import services as attendance_services
from smass_attendance.models import LEAVE_SUBMITTED, LeaveRequest
from smass_forum import services as forum_services
from smass_forum.models import Announcement
from smass_facilities.models import Building, Room
from smass_organization.models import (
    OrganizationMembership, OrganizationUnit, StudentRecord,
)
from smass_organization.services import create_unit


class WorkspaceFixture(TestCase):
    """三端测试共用的最小数据集。"""

    @classmethod
    def setUpTestData(cls):
        account_services.ensure_role_groups()
        cls.password = 'Test#2026pass'

        cls.college = create_unit(code='T-COL', name='信息工程学院',
                                  unit_type='college')
        cls.major = create_unit(code='T-MAJ', name='软件工程',
                                unit_type='major', parent=cls.college)
        cls.klass = create_unit(code='T-CLS', name='软工2401',
                                unit_type='class', parent=cls.major)
        cls.other_college = create_unit(code='T-COL2', name='其他学院',
                                        unit_type='college')
        cls.other_major = create_unit(code='T-MAJ2', name='机械工程',
                                      unit_type='major', parent=cls.other_college)
        cls.other_class = create_unit(code='T-CLS2', name='机械2401',
                                      unit_type='class', parent=cls.other_major)

        def make_account(login_name, display, person_type, roles, scope=''):
            account = Account.objects.create_user(
                login_name, cls.password, display_name=display,
                person_type=person_type)
            account.must_change_password = False
            if scope:
                account.scope_college = scope
            account.save()
            for role in roles:
                account_services.grant_role(account, role)
            return account

        cls.admin = make_account('t_admin', '测试管理员', 'admin',
                                 ['system_admin'])
        cls.college_admin = make_account('t_college', '测试学院管理员', 'admin',
                                         ['college_admin'], scope='信息工程学院')
        cls.teacher = make_account('t_teacher', '测试教师', 'teacher', ['teacher'])
        cls.teacher2 = make_account('t_teacher2', '测试教师二', 'teacher',
                                    ['teacher'])
        cls.counselor = make_account('t_counselor', '测试辅导员', 'teacher',
                                     ['teacher'])
        cls.student = make_account('t_student', '测试学生', 'student', ['student'])
        cls.student2 = make_account('t_student2', '测试学生二', 'student',
                                    ['student'])
        cls.outsider = make_account('t_outsider', '外院学生', 'student', ['student'])
        cls.nobody = make_account('t_nobody', '无角色账号', 'student', [])

        cls.student_profile = StudentProfile.objects.create(
            account=cls.student, student_no='T2024001', name='测试学生',
            college_name='信息工程学院', classes_name='软工2401')
        StudentProfile.objects.create(
            account=cls.student2, student_no='T2024002', name='测试学生二',
            college_name='信息工程学院', classes_name='软工2401')
        StudentProfile.objects.create(
            account=cls.outsider, student_no='T2024003', name='外院学生',
            college_name='其他学院', classes_name='机械2401')
        TeacherProfile.objects.create(
            account=cls.teacher, teacher_no='TT0001', name='测试教师',
            college_name='信息工程学院')

        cls.record = StudentRecord.objects.create(
            student_no='T2024001', name='测试学生', account=cls.student,
            unit=cls.klass, status='enrolled', enrolled_at=date(2024, 9, 1),
            extra={'dormitory': {'building': '测试公寓', 'room': '101',
                                 'bed': '1 号床', 'roommates': ['测试学生二']}})
        cls.record2 = StudentRecord.objects.create(
            student_no='T2024002', name='测试学生二', account=cls.student2,
            unit=cls.klass, status='enrolled', enrolled_at=date(2024, 9, 1))
        cls.outsider_record = StudentRecord.objects.create(
            student_no='T2024003', name='外院学生', account=cls.outsider,
            unit=cls.other_class, status='enrolled', enrolled_at=date(2024, 9, 1))

        OrganizationMembership.objects.create(
            account=cls.counselor, unit=cls.klass, role='counselor',
            started_at=date(2024, 9, 1))

        cls.year = AcademicYear.objects.create(
            code='T-2024', start_date=date(2024, 9, 1),
            end_date=date(2025, 8, 31), is_active=True)
        cls.term = AcademicTerm.objects.create(
            year=cls.year, semester='1', name='2024-2025-1',
            start_date=date(2024, 9, 1), end_date=date(2025, 1, 15),
            is_active=True)
        cls.course = Course.objects.create(
            code='T-CS101', title='测试课程', credit=3)
        cls.section = TeachingSection.objects.create(
            term=cls.term, course=cls.course, code='A', capacity=40)
        TeachingAssignment.objects.create(section=cls.section, account=cls.teacher)
        Enrollment.objects.create(section=cls.section, account=cls.student)
        Enrollment.objects.create(section=cls.section, account=cls.student2)

        cls.leave = attendance_services.submit_leave(
            cls.record, 'sick', date.today(), date.today() + timedelta(days=1),
            '测试请假', cls.student)

        cls.building = Building.objects.create(
            code='T-B-A', name='测试教学楼', campus='主校区')
        cls.room = Room.objects.create(
            code='T-ROOM-1', name='测试研讨室', building=cls.building,
            room_type='meeting', capacity=20, status='open',
            requires_approval=True, is_active=True)

        cls.announcement = forum_services.create_announcement(
            cls.admin, '测试公告', '测试公告正文', 'student')
        forum_services.publish_announcement(cls.announcement, cls.admin)

    def login(self, account):
        self.client.force_login(account)


class AuthFlowTests(WorkspaceFixture):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get('/student/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.headers['Location'])
        self.assertIn('next=/student/', response.headers['Location'])

    def test_login_page_renders(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '统一登录入口')

    def test_login_lands_student(self):
        response = self.client.post('/login/', {
            'login_name': 't_student', 'password': self.password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/student/')

    def test_login_lands_teacher(self):
        response = self.client.post('/login/', {
            'login_name': 't_teacher', 'password': self.password})
        self.assertEqual(response.headers['Location'], '/teacher/')

    def test_login_lands_admin(self):
        response = self.client.post('/login/', {
            'login_name': 't_admin', 'password': self.password})
        self.assertEqual(response.headers['Location'], '/admin/')

    def test_login_lands_no_role(self):
        response = self.client.post('/login/', {
            'login_name': 't_nobody', 'password': self.password})
        self.assertEqual(response.headers['Location'], '/no-role/')
        self.login(self.nobody)
        self.assertEqual(self.client.get('/no-role/').status_code, 403)

    def test_logout_requires_post(self):
        self.login(self.student)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        response = self.client.post('/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/student/').status_code, 302)


class GuardMatrixTests(WorkspaceFixture):
    def test_student_cannot_enter_admin(self):
        self.login(self.student)
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_student_cannot_enter_teacher(self):
        self.login(self.student)
        self.assertEqual(self.client.get('/teacher/').status_code, 403)

    def test_teacher_cannot_enter_student(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get('/student/').status_code, 403)

    def test_teacher_cannot_enter_admin(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_counselor_can_open_classes(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get('/teacher/classes/').status_code, 200)

    def test_plain_teacher_cannot_open_classes(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get('/teacher/classes/').status_code, 403)

    def test_college_admin_cannot_open_settings(self):
        self.login(self.college_admin)
        self.assertEqual(self.client.get('/admin/settings/').status_code, 403)

    def test_system_admin_can_open_settings(self):
        self.login(self.admin)
        self.assertEqual(self.client.get('/admin/settings/').status_code, 200)

    def test_system_admin_without_student_role_is_denied_student(self):
        self.login(self.admin)
        self.assertEqual(self.client.get('/student/').status_code, 403)


class StudentWorkspaceTests(WorkspaceFixture):
    PAGES = [
        '/student/', '/student/timetable/', '/student/courses/',
        '/student/record/', '/student/attendance/', '/student/fees/',
        '/student/bookings/', '/student/activities/', '/student/volunteer/',
        '/student/clubs/', '/student/organizations/', '/student/dormitory/',
        '/student/notices/',
    ]

    def test_all_student_pages_render(self):
        self.login(self.student)
        for url in self.PAGES:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_timetable_and_course_visible(self):
        self.login(self.student)
        body = self.client.get('/student/courses/').content.decode('utf-8')
        self.assertIn('测试课程', body)

    def test_student_submits_leave(self):
        self.login(self.student)
        start = date.today() + timedelta(days=10)
        response = self.client.post('/student/attendance/leave/', {
            'leave_type': 'personal',
            'start_date': start.isoformat(),
            'end_date': (start + timedelta(days=1)).isoformat(),
            'reason': '产品层测试请假',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LeaveRequest.objects.filter(
            record=self.record, reason='产品层测试请假').exists())

    def test_student_creates_room_booking(self):
        from smass_facilities.models import RoomBooking

        self.login(self.student)
        response = self.client.post('/student/bookings/create/', {
            'room': self.room.pk,
            'start_at': '2027-03-01T14:00',
            'end_at': '2027-03-01T16:00',
            'purpose': '产品层测试预约',
            'attendees': '5',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(RoomBooking.objects.filter(
            account=self.student, purpose='产品层测试预约').exists())

    def test_student_cancels_own_booking(self):
        from smass_facilities.models import RoomBooking

        self.login(self.student)
        self.client.post('/student/bookings/create/', {
            'room': self.room.pk,
            'start_at': '2027-03-02T14:00',
            'end_at': '2027-03-02T16:00',
            'purpose': '产品层测试取消',
        })
        booking = RoomBooking.objects.filter(
            account=self.student, purpose='产品层测试取消').first()
        self.assertIsNotNone(booking)
        response = self.client.post(
            '/student/bookings/{}/cancel/'.format(booking.pk), {'reason': '测试取消'})
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')

    def test_student_cannot_cancel_others_leave(self):
        other_leave = attendance_services.submit_leave(
            self.record2, 'personal', date.today() + timedelta(days=20),
            date.today() + timedelta(days=21), '他人请假', self.student2)
        self.login(self.student)
        self.client.post('/student/attendance/leave/{}/cancel/'.format(
            other_leave.pk))
        other_leave.refresh_from_db()
        self.assertEqual(other_leave.status, LEAVE_SUBMITTED)


class TeacherWorkspaceTests(WorkspaceFixture):
    PAGES = [
        '/teacher/', '/teacher/courses/', '/teacher/sections/',
        '/teacher/timetable/', '/teacher/attendance/', '/teacher/students/',
        '/teacher/approvals/', '/teacher/notices/',
    ]

    def test_all_teacher_pages_render(self):
        self.login(self.teacher)
        for url in self.PAGES:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_teacher_approves_leave_and_student_sees_it(self):
        self.login(self.teacher)
        response = self.client.post(
            '/teacher/approvals/leave/{}/approve/'.format(self.leave.pk))
        self.assertEqual(response.status_code, 302)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'approved')

        self.login(self.student)
        body = self.client.get('/student/attendance/').content.decode('utf-8')
        self.assertIn('已批准', body)

    def test_teacher_cannot_view_student_outside_sections(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(
            '/teacher/students/{}/'.format(self.outsider_record.pk)).status_code,
            403)

    def test_teacher_can_view_own_student(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(
            '/teacher/students/{}/'.format(self.record.pk)).status_code, 200)


class CounselorScopeTests(WorkspaceFixture):
    def test_counselor_sees_own_classes(self):
        self.login(self.counselor)
        response = self.client.get('/teacher/classes/')
        self.assertContains(response, '软工2401')

    def test_counselor_students_limited_to_scope(self):
        self.login(self.counselor)
        response = self.client.get('/teacher/counselor/students/')
        self.assertContains(response, '测试学生')
        self.assertNotContains(response, '外院学生')

    def test_counselor_cannot_view_outside_student(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(
            '/teacher/students/{}/'.format(self.outsider_record.pk)).status_code,
            403)

    def test_counselor_leave_review_listed(self):
        self.login(self.counselor)
        response = self.client.get('/teacher/counselor/leaves/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '测试学生')


class CounselorTeachingOverlapTests(WorkspaceFixture):
    """兼课辅导员：教学班与负责班级取并集，列表/详情一致。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from smass_academic.models import (
            Course, Enrollment, TeachingAssignment, TeachingSection,
        )

        cls.course2 = Course.objects.create(
            code='T-CS102', title='测试课程二', credit=2)
        cls.section2 = TeachingSection.objects.create(
            term=cls.term, course=cls.course2, code='B', capacity=20)
        TeachingAssignment.objects.create(section=cls.section2,
                                         account=cls.counselor)
        Enrollment.objects.create(section=cls.section2, account=cls.outsider)

        cls.stranger = Account.objects.create_user(
            't_stranger', cls.password, display_name='无关学生',
            person_type='student')
        cls.stranger.must_change_password = False
        cls.stranger.save()
        StudentProfile.objects.create(
            account=cls.stranger, student_no='T2024099', name='无关学生',
            college_name='其他学院', classes_name='机械2401')
        cls.stranger_record = StudentRecord.objects.create(
            student_no='T2024099', name='无关学生', account=cls.stranger,
            unit=cls.other_class, status='enrolled', enrolled_at=date(2024, 9, 1))

    def test_counselor_sees_teaching_section_student(self):
        self.login(self.counselor)
        response = self.client.get(
            '/teacher/students/{}/'.format(self.outsider_record.pk))
        self.assertEqual(response.status_code, 200)

    def test_list_merges_teaching_and_counselor_scope(self):
        self.login(self.counselor)
        body = self.client.get('/teacher/students/').content.decode('utf-8')
        self.assertIn('T2024003', body)  # 教学班学生（外院）
        self.assertIn('T2024001', body)  # 负责班级学生

    def test_unrelated_student_still_403(self):
        self.login(self.counselor)
        response = self.client.get(
            '/teacher/students/{}/'.format(self.stranger_record.pk))
        self.assertEqual(response.status_code, 403)

    def test_revoked_counselor_loses_class_scope(self):
        from django.utils import timezone

        from smass_organization.models import OrganizationMembership

        OrganizationMembership.objects.filter(
            account=self.counselor).update(ended_at=timezone.now())
        self.login(self.counselor)
        response = self.client.get(
            '/teacher/students/{}/'.format(self.record.pk))
        self.assertEqual(response.status_code, 403)


class AdminConsoleTests(WorkspaceFixture):
    PAGES = [
        '/admin/', '/admin/users/', '/admin/roles/', '/admin/organizations/',
        '/admin/records/', '/admin/record-changes/', '/admin/academics/',
        '/admin/sections/', '/admin/scheduling/', '/admin/facilities/',
        '/admin/booking-approvals/', '/admin/approvals/', '/admin/workflows/',
        '/admin/activities/', '/admin/clubs/', '/admin/notices/',
        '/admin/data-exchange/', '/admin/monitoring/', '/admin/audit/',
    ]

    def test_all_admin_pages_render(self):
        self.login(self.admin)
        for url in self.PAGES:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_college_admin_scope_excludes_other_college(self):
        self.login(self.college_admin)
        response = self.client.get('/admin/records/')
        self.assertContains(response, '测试学生')
        self.assertNotContains(response, '外院学生')

    def test_college_admin_cannot_view_other_college_record(self):
        self.login(self.college_admin)
        self.assertEqual(self.client.get(
            '/admin/records/T2024003/').status_code, 403)

    def test_system_admin_can_view_any_record(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(
            '/admin/records/T2024003/').status_code, 200)

    def test_create_course_from_console(self):
        self.login(self.admin)
        response = self.client.post('/admin/academics/course/', {
            'code': 'T-CS999', 'title': '控制台课程', 'credit': '2',
            'course_type': '选修'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Course.objects.filter(code='T-CS999').exists())

    def test_college_admin_cannot_create_course(self):
        self.login(self.college_admin)
        response = self.client.post('/admin/academics/course/', {
            'code': 'T-CS998', 'title': '越权课程', 'credit': '2'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.filter(code='T-CS998').exists())

    def test_grant_role_changes_landing(self):
        self.login(self.admin)
        self.client.post('/admin/users/{}/role/'.format(self.student.pk), {
            'action': 'grant', 'role': 'teacher'})
        self.student.refresh_from_db()
        self.assertIn('teacher', set(self.student.active_roles()))
        self.login(self.student)
        response = self.client.post('/login/', {
            'login_name': 't_student', 'password': self.password})
        self.assertEqual(response.headers['Location'], '/teacher/')

    def test_admin_publishes_announcement_visible_to_student(self):
        self.login(self.admin)
        self.client.post('/admin/notices/create/', {
            'title': '控制台公告', 'body': '正文', 'audience': 'student',
            'publish': '1'})
        self.assertTrue(Announcement.objects.filter(
            title='控制台公告', status='published').exists())
        self.login(self.student)
        body = self.client.get('/student/notices/').content.decode('utf-8')
        self.assertIn('控制台公告', body)

    def test_admin_creates_room(self):
        from smass_facilities.models import Room

        self.login(self.admin)
        response = self.client.post('/admin/facilities/rooms/create/', {
            'building': self.building.pk, 'code': 'T-A301',
            'name': '测试研讨室', 'room_type': 'meeting', 'capacity': '20',
            'requires_approval': '1'})
        self.assertEqual(response.status_code, 302)
        room = Room.objects.get(code='T-A301')
        self.assertEqual(room.status, 'open')
        self.assertTrue(room.requires_approval)

    def test_college_admin_cannot_create_room(self):
        from smass_facilities.models import Room

        self.login(self.college_admin)
        response = self.client.post('/admin/facilities/rooms/create/', {
            'building': self.building.pk, 'code': 'T-A302',
            'name': '越权场地', 'room_type': 'meeting', 'capacity': '10'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Room.objects.filter(code='T-A302').exists())


class SharedServiceTests(WorkspaceFixture):
    def test_profile_and_notifications_for_all_roles(self):
        for account in (self.student, self.teacher, self.admin):
            self.login(account)
            with self.subTest(account=account.login_name):
                self.assertEqual(self.client.get('/profile/').status_code, 200)
                self.assertEqual(self.client.get(
                    '/notifications/').status_code, 200)

    def test_legacy_entry_redirects(self):
        self.login(self.admin)
        for url, target in (('/r10/', '/admin/'), ('/hub/', '/')):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['Location'], target)
