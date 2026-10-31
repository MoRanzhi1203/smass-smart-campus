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


class StudentCourseEnrollTests(WorkspaceFixture):
    """学生选课/退课：容量、持久化、越权。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from smass_academic.models import Course, TeachingSection

        cls.course_b = Course.objects.create(
            code='T-CS103', title='测试课程三', credit=2)
        cls.section_b = TeachingSection.objects.create(
            term=cls.term, course=cls.course_b, code='C', capacity=2)
        cls.course_c = Course.objects.create(
            code='T-CS104', title='测试课程四', credit=1)
        cls.section_c = TeachingSection.objects.create(
            term=cls.term, course=cls.course_c, code='D', capacity=1)
        Enrollment.objects.create(section=cls.section_c, account=cls.student2,
                                  status='enrolled')

    def test_enroll_available_section(self):
        self.login(self.student)
        response = self.client.post(
            '/student/courses/{}/enroll/'.format(self.section_b.pk), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Enrollment.objects.filter(
            section=self.section_b, account=self.student,
            status='enrolled').exists())
        self.assertContains(response, '已选上')

    def test_enroll_capacity_full_shows_error(self):
        self.login(self.student)
        response = self.client.post(
            '/student/courses/{}/enroll/'.format(self.section_c.pk), follow=True)
        self.assertFalse(Enrollment.objects.filter(
            section=self.section_c, account=self.student).exists())
        self.assertContains(response, '容量已满')

    def test_drop_own_enrollment(self):
        self.login(self.student)
        enrollment = Enrollment.objects.get(
            section=self.section, account=self.student)
        response = self.client.post(
            '/student/courses/enrollments/{}/drop/'.format(enrollment.pk),
            follow=True)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, 'dropped')
        self.assertContains(response, '已退选')

    def test_cannot_drop_others_enrollment(self):
        self.login(self.student)
        other = Enrollment.objects.get(
            section=self.section, account=self.student2)
        response = self.client.post(
            '/student/courses/enrollments/{}/drop/'.format(other.pk))
        self.assertEqual(response.status_code, 404)


class StudentAttendanceActionTests(WorkspaceFixture):
    """学生签到、补签、销假。"""

    def _open_session(self, code='A1B2C3'):
        from django.utils import timezone

        from smass_attendance.models import AttendanceSession

        return AttendanceSession.objects.create(
            unit=self.klass, session_date=date.today(), period='第1-2节',
            topic='测试考勤', status='open', code=code,
            code_expires_at=timezone.now() + timedelta(minutes=10),
            created_by='t_teacher')

    def test_sign_in_with_code(self):
        from smass_attendance.models import AttendanceRecord

        session = self._open_session()
        self.login(self.student)
        response = self.client.post(
            '/student/attendance/{}/sign/'.format(session.pk),
            {'code': 'A1B2C3'}, follow=True)
        self.assertContains(response, '签到成功')
        self.assertTrue(AttendanceRecord.objects.filter(
            session=session, record=self.record, status='present').exists())

    def test_sign_in_wrong_code(self):
        from smass_attendance.models import AttendanceRecord

        session = self._open_session()
        self.login(self.student)
        response = self.client.post(
            '/student/attendance/{}/sign/'.format(session.pk),
            {'code': 'WRONG'}, follow=True)
        self.assertContains(response, '签到码')
        self.assertFalse(AttendanceRecord.objects.filter(
            session=session, record=self.record).exists())

    def test_makeup_submit(self):
        from smass_attendance.models import (
            AttendanceRecord, AttendanceSession, MakeupRequest,
        )

        session = AttendanceSession.objects.create(
            unit=self.klass,
            session_date=date.today() - timedelta(days=2),
            period='第3-4节', status='closed')
        AttendanceRecord.objects.create(
            session=session, record=self.record, status='absent')
        self.login(self.student)
        response = self.client.post(
            '/student/attendance/{}/makeup/'.format(session.pk),
            {'reason': '身体不适未签到'}, follow=True)
        self.assertContains(response, '补签申请已提交')
        self.assertTrue(MakeupRequest.objects.filter(
            record=self.record, session=session, status='submitted').exists())

    def test_close_approved_leave(self):
        from smass_attendance.models import LeaveRequest

        leave = LeaveRequest.objects.create(
            record=self.record, leave_type='sick',
            start_date=date.today() - timedelta(days=3),
            end_date=date.today() - timedelta(days=1),
            reason='测试销假', status='approved',
            submitted_by=str(self.student.pk), reviewed_by='t_teacher')
        self.login(self.student)
        response = self.client.post(
            '/student/attendance/leave/{}/close/'.format(leave.pk),
            follow=True)
        leave.refresh_from_db()
        self.assertEqual(leave.status, 'closed')
        self.assertContains(response, '已销假')


class NotificationLinkageTests(WorkspaceFixture):
    """F02：审批结果写站内通知（幂等 event_key）。"""

    def test_leave_approval_notifies_student(self):
        from smass_attendance import services as attendance_services
        from smass_workflow.models import Notification

        attendance_services.approve_leave(self.leave, self.teacher)
        self.assertTrue(Notification.objects.filter(
            recipient=self.student.login_name,
            event_key='leave:{}:approved'.format(self.leave.pk),
            title='请假已批准').exists())

    def test_booking_approval_notifies_applicant(self):
        from django.utils import timezone

        from smass_facilities import services as facility_services
        from smass_facilities.models import RoomBooking
        from smass_workflow.models import Notification

        start = timezone.now() + timedelta(days=5)
        booking = RoomBooking.objects.create(
            room=self.room, account=self.student,
            start_at=start, end_at=start + timedelta(hours=2),
            purpose='通知联动测试', status='pending')
        facility_services.approve_booking(booking, self.admin)
        self.assertTrue(Notification.objects.filter(
            recipient=self.student.login_name,
            event_key='booking:{}:approved'.format(booking.pk),
            title='场地预约已批准').exists())


class StudentActivityCheckinTests(WorkspaceFixture):
    """C03：活动详情与签到。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.utils import timezone

        from smass_activities.models import Activity, ActivityRegistration

        now = timezone.now()
        cls.activity = Activity.objects.create(
            title='测试活动', category='second_class',
            start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1),
            location='测试教室', capacity=10, credit_points=1,
            status='published', checkin_code='ACT123', created_by='t_admin')
        cls.registration = ActivityRegistration.objects.create(
            activity=cls.activity, record=cls.record, status='registered')

    def test_detail_page_renders(self):
        self.login(self.student)
        response = self.client.get(
            '/student/activities/{}/'.format(self.activity.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '测试活动')

    def test_check_in_success(self):
        self.login(self.student)
        response = self.client.post(
            '/student/activities/registrations/{}/checkin/'.format(
                self.registration.pk),
            {'code': 'ACT123'}, follow=True)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, 'checked_in')
        self.assertContains(response, '签到成功')

    def test_check_in_outside_window(self):
        from django.utils import timezone

        self.activity.start_at = timezone.now() + timedelta(days=1)
        self.activity.end_at = timezone.now() + timedelta(days=1, hours=2)
        self.activity.save(update_fields=['start_at', 'end_at'])
        self.login(self.student)
        response = self.client.post(
            '/student/activities/registrations/{}/checkin/'.format(
                self.registration.pk),
            {'code': 'ACT123'}, follow=True)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, 'registered')
        self.assertIn('签到时间', response.content.decode('utf-8'))


class TeacherBulkAttendanceTests(WorkspaceFixture):
    """D02：教师批量登记与对象级权限。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from smass_attendance.models import AttendanceSession

        cls.session = AttendanceSession.objects.create(
            unit=cls.klass, session_date=date.today(), period='第1-2节',
            status='open', code='BULK01', created_by=cls.teacher.login_name)

    def test_bulk_mark_records_all_students(self):
        from smass_attendance.models import AttendanceRecord

        self.login(self.teacher)
        response = self.client.post(
            '/teacher/attendance/{}/bulk/'.format(self.session.pk), {
                'status_{}'.format(self.record.pk): 'present',
                'status_{}'.format(self.record2.pk): 'absent',
            }, follow=True)
        self.assertContains(response, '已批量登记 2 人')
        self.assertEqual(AttendanceRecord.objects.get(
            session=self.session, record=self.record).status, 'present')
        self.assertEqual(AttendanceRecord.objects.get(
            session=self.session, record=self.record2).status, 'absent')

    def test_other_teacher_cannot_bulk_mark(self):
        from smass_attendance.models import AttendanceRecord

        self.login(self.teacher2)
        self.client.post(
            '/teacher/attendance/{}/bulk/'.format(self.session.pk), {
                'status_{}'.format(self.record.pk): 'present'})
        self.assertFalse(AttendanceRecord.objects.filter(
            session=self.session).exists())


class TeacherApprovalReasonTests(WorkspaceFixture):
    """D03：驳回理由必须落库并同步学生端。"""

    def test_reject_leave_with_reason(self):
        self.login(self.teacher)
        response = self.client.post(
            '/teacher/approvals/leave/{}/reject/'.format(self.leave.pk),
            {'reason': '材料不齐'}, follow=True)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'rejected')
        self.assertEqual(self.leave.reject_reason, '材料不齐')
        self.assertContains(response, '请假已驳回')


class AdminOrganizationTests(WorkspaceFixture):
    """E01：组织架构 CRUD、层级校验与越权。"""

    def test_create_unit(self):
        from smass_organization.models import OrganizationUnit

        self.login(self.admin)
        response = self.client.post('/admin/organizations/create/', {
            'unit_type': 'college', 'code': 'T-COL-NEW',
            'name': '新学院'}, follow=True)
        self.assertContains(response, '组织单元已创建')
        self.assertTrue(OrganizationUnit.objects.filter(
            code='T-COL-NEW', name='新学院').exists())

    def test_college_admin_cannot_create(self):
        from smass_organization.models import OrganizationUnit

        self.login(self.college_admin)
        response = self.client.post('/admin/organizations/create/', {
            'unit_type': 'college', 'code': 'T-COL-X', 'name': '越权学院'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(OrganizationUnit.objects.filter(
            code='T-COL-X').exists())

    def test_deactivate_blocked_by_students(self):
        self.login(self.admin)
        response = self.client.post(
            '/admin/organizations/{}/update/'.format(self.klass.pk),
            {'action': 'status', 'status': 'inactive'}, follow=True)
        self.klass.refresh_from_db()
        self.assertEqual(self.klass.status, 'active')
        self.assertContains(response, '仍有学籍')

    def test_move_unit(self):
        self.login(self.admin)
        response = self.client.post(
            '/admin/organizations/{}/update/'.format(self.klass.pk),
            {'action': 'move', 'parent': self.other_major.pk}, follow=True)
        self.klass.refresh_from_db()
        self.assertEqual(self.klass.parent_id, self.other_major.pk)


class AdminTeacherTests(WorkspaceFixture):
    """E02：教师账号与档案 CRUD。"""

    def test_create_teacher_creates_account_profile_role(self):
        from r21_account.models import Account, TeacherProfile

        self.login(self.admin)
        response = self.client.post('/admin/teachers/create/', {
            'teacher_no': 'TT9001', 'name': '新教师',
            'college_name': '信息工程学院', 'password': 'Test#2026pass',
        }, follow=True)
        self.assertContains(response, '教师已创建')
        account = Account.objects.get(login_name='TT9001')
        self.assertEqual(account.person_type, 'teacher')
        self.assertTrue(account.check_password('Test#2026pass'))
        self.assertGreaterEqual(len(account.active_roles()), 1)
        self.assertTrue(TeacherProfile.objects.filter(
            account=account, teacher_no='TT9001', name='新教师').exists())

    def test_duplicate_teacher_no_rejected(self):
        from r21_account.models import Account

        self.login(self.admin)
        response = self.client.post('/admin/teachers/create/', {
            'teacher_no': 'TT0001', 'name': '重复教师',
            'college_name': '', 'password': 'Test#2026pass',
        }, follow=True)
        self.assertContains(response, '已存在')
        from r21_account.models import TeacherProfile

        self.assertEqual(TeacherProfile.objects.filter(
            teacher_no='TT0001').count(), 1)
        self.assertFalse(Account.objects.filter(login_name='TT0001').exists())

    def test_college_admin_cannot_create_teacher(self):
        from r21_account.models import Account

        self.login(self.college_admin)
        response = self.client.post('/admin/teachers/create/', {
            'teacher_no': 'TT9002', 'name': '越权教师',
            'college_name': '', 'password': 'Test#2026pass',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Account.objects.filter(login_name='TT9002').exists())

    def test_update_teacher_syncs_display_name(self):
        from r21_account.models import TeacherProfile

        profile = TeacherProfile.objects.get(teacher_no='TT0001')
        self.login(self.admin)
        response = self.client.post(
            '/admin/teachers/{}/update/'.format(profile.pk), {
                'name': '教师改名', 'college_name': '信息工程学院'}, follow=True)
        self.assertContains(response, '教师档案已更新')
        profile.refresh_from_db()
        self.assertEqual(profile.name, '教师改名')
        self.assertEqual(profile.account.display_name, '教师改名')


class StudentClubTests(WorkspaceFixture):
    """C04：社团详情、申请与退社。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from smass_clubs.models import Club

        cls.club = Club.objects.create(
            code='T-CLUB-1', name='测试社团', category='academic',
            status='active', description='用于测试的社团')

    def test_detail_page_renders(self):
        self.login(self.student)
        response = self.client.get('/student/clubs/{}/'.format(self.club.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '测试社团')

    def test_apply_then_leave(self):
        from smass_clubs.models import ClubMembership

        self.login(self.student)
        self.client.post(
            '/student/clubs/{}/apply/'.format(self.club.pk), follow=True)
        membership = ClubMembership.objects.get(
            club=self.club, record=self.record)
        self.assertEqual(membership.status, 'pending')
        self.client.post(
            '/student/clubs/memberships/{}/leave/'.format(membership.pk),
            follow=True)
        membership.refresh_from_db()
        self.assertEqual(membership.status, 'left')

    def test_cannot_leave_others_membership(self):
        from smass_clubs.models import ClubMembership

        other = ClubMembership.objects.create(
            club=self.club, record=self.record2, status='active')
        self.login(self.student)
        response = self.client.post(
            '/student/clubs/memberships/{}/leave/'.format(other.pk),
            follow=True)
        other.refresh_from_db()
        self.assertEqual(other.status, 'active')
        self.assertContains(response, '只能退出自己的社团')


class StudentBookingAndFeeTests(WorkspaceFixture):
    """C05/C06：场地签到释放与账单退费。"""

    def _booking(self, status='approved', account=None):
        from django.utils import timezone

        from smass_facilities.models import RoomBooking

        start = timezone.now() + timedelta(days=3)
        return RoomBooking.objects.create(
            room=self.room, account=account or self.student,
            start_at=start, end_at=start + timedelta(hours=1),
            purpose='V2 测试预约', status=status)

    def test_booking_checkin_and_release(self):
        booking = self._booking()
        self.login(self.student)
        self.client.post(
            '/student/bookings/{}/checkin/'.format(booking.pk), follow=True)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'checked_in')
        self.client.post(
            '/student/bookings/{}/release/'.format(booking.pk), follow=True)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'released')

    def test_booking_checkin_others_rejected(self):
        booking = self._booking(account=self.student2)
        self.login(self.student)
        response = self.client.post(
            '/student/bookings/{}/checkin/'.format(booking.pk), follow=True)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'approved')
        self.assertContains(response, '不属于你')

    def test_fee_refund_request(self):
        from decimal import Decimal

        from smass_finance.models import Bill, RefundRequest

        bill = Bill.objects.create(
            bill_no='T-BILL-1', record=self.record, term='2024-2025-1',
            total=Decimal('100.00'), paid=Decimal('100.00'), status='paid')
        self.login(self.student)
        response = self.client.post(
            '/student/fees/{}/refund/'.format(bill.pk),
            {'amount': '30', 'reason': '多缴退费'}, follow=True)
        self.assertContains(response, '退费申请已提交')
        self.assertTrue(RefundRequest.objects.filter(
            bill=bill, amount=Decimal('30.00'), status='submitted').exists())

    def test_fee_detail_renders(self):
        from decimal import Decimal

        from smass_finance.models import Bill

        bill = Bill.objects.create(
            bill_no='T-BILL-2', record=self.record, term='2024-2025-1',
            total=Decimal('50.00'), paid=Decimal('0.00'), status='unpaid')
        self.login(self.student)
        response = self.client.get('/student/fees/{}/'.format(bill.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'T-BILL-2')
        self.assertContains(response, '申请退费')


class AdminSchedulingTests(WorkspaceFixture):
    """E03：排课批次创建、求解、发布门禁。"""

    def test_create_solve_publish(self):
        from smass_scheduling.models import ScheduleRun

        self.login(self.admin)
        response = self.client.post(
            '/admin/scheduling/create/', {'term': self.term.pk}, follow=True)
        self.assertContains(response, '排课批次已创建')
        run = ScheduleRun.objects.get(term=self.term)
        self.assertEqual(run.status, 'draft')

        self.client.post(
            '/admin/scheduling/{}/solve/'.format(run.pk), follow=True)
        run.refresh_from_db()
        self.assertIn(run.status, ('solved', 'infeasible'))
        if run.status == 'solved':
            self.client.post(
                '/admin/scheduling/{}/publish/'.format(run.pk), follow=True)
            run.refresh_from_db()
            self.assertEqual(run.status, 'published')

    def test_duplicate_unpublished_run_rejected(self):
        from smass_scheduling.models import ScheduleRun

        ScheduleRun.objects.create(term=self.term, status='draft')
        self.login(self.admin)
        response = self.client.post(
            '/admin/scheduling/create/', {'term': self.term.pk}, follow=True)
        self.assertContains(response, '已有未发布的排课批次')
        self.assertEqual(ScheduleRun.objects.filter(term=self.term).count(), 1)

    def test_publish_draft_rejected(self):
        from smass_scheduling.models import ScheduleRun

        run = ScheduleRun.objects.create(term=self.term, status='draft')
        self.login(self.admin)
        response = self.client.post(
            '/admin/scheduling/{}/publish/'.format(run.pk), follow=True)
        self.assertContains(response, '只有已求解的批次可以发布')
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')

    def test_college_admin_cannot_solve_or_publish(self):
        from smass_scheduling.models import ScheduleRun

        run = ScheduleRun.objects.create(term=self.term, status='draft')
        self.login(self.college_admin)
        response = self.client.post(
            '/admin/scheduling/{}/solve/'.format(run.pk))
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
