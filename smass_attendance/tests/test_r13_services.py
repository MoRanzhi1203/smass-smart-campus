"""R13 服务层：签到、关闭会话、请假销假与补签。

运行::

    python manage.py test smass_attendance.tests.test_r13_services --settings=smass.settings_r13
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)

from smass_attendance import services
from smass_attendance.models import (
    LEAVE_PERSONAL,
    RECORD_ABSENT,
    RECORD_LATE,
    RECORD_LEAVE,
    RECORD_PRESENT,
    AttendanceRecord,
    AttendanceSession,
    LeaveRequest,
    MakeupRequest,
)

PASSWORD = 'R13Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class AttendanceBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='计算机学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='计科', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='计科一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.klass2 = OrganizationUnit.objects.create(
            code='CL02', name='计科二班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('r13teacher', [RoleCode.TEACHER], person_type='teacher')
        self.student = make_account('r13stu', [RoleCode.STUDENT])
        self.student2 = make_account('r13stu2', [RoleCode.STUDENT])

        self.me = StudentRecord.objects.create(
            student_no='S6001', name='考勤学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S6002', name='同班同学', unit=self.klass, account=self.student2)

        self.session = services.create_session(
            self.klass, timezone.localdate(), '第1-2节', self.teacher, topic='数据结构')


class SessionTests(AttendanceBase):
    def test_create_session_generates_code(self):
        self.assertEqual(len(self.session.code), 6)
        self.assertTrue(self.session.code.isdigit())
        self.assertEqual(self.session.status, 'open')
        self.assertIsNotNone(self.session.code_expires_at)

    def test_duplicate_slot_rejected(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.create_session(
                self.klass, timezone.localdate(), '第1-2节', self.teacher)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_SESSION')

    def test_student_cannot_create_session(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_session(self.klass, timezone.localdate(), '第3-4节', self.student)

    def test_non_class_unit_rejected(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.create_session(self.major, timezone.localdate(), '第3-4节', self.teacher)
        self.assertEqual(ctx.exception.code, 'BAD_UNIT')

    def test_sign_in_success(self):
        record, created = services.sign_in(
            self.session, self.student, self.session.code, ip='127.0.0.1')
        self.assertTrue(created)
        self.assertEqual(record.status, RECORD_PRESENT)
        self.assertEqual(record.source, 'self')

    def test_sign_in_wrong_code(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.sign_in(self.session, self.student, '000000')
        self.assertEqual(ctx.exception.code, 'BAD_CODE')

    def test_sign_in_expired_code(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            code_expires_at=timezone.now() - dt.timedelta(minutes=1))
        self.session.refresh_from_db()
        with self.assertRaises(services.AttendanceError) as ctx:
            services.sign_in(self.session, self.student, self.session.code)
        self.assertEqual(ctx.exception.code, 'CODE_EXPIRED')

    def test_sign_in_other_class_rejected(self):
        outsider = StudentRecord.objects.create(
            student_no='S6099', name='外班', unit=self.klass2, account=None)
        account = make_account('r13out', [RoleCode.STUDENT])
        outsider.account = account
        outsider.save(update_fields=['account'])
        with self.assertRaises(services.AttendanceError) as ctx:
            services.sign_in(self.session, account, self.session.code)
        self.assertEqual(ctx.exception.code, 'NOT_IN_CLASS')

    def test_sign_in_is_idempotent(self):
        first, created1 = services.sign_in(self.session, self.student, self.session.code)
        second, created2 = services.sign_in(self.session, self.student, self.session.code)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AttendanceRecord.objects.filter(
            session=self.session, record=self.me).count(), 1)

    def test_late_detection(self):
        AttendanceSession.objects.filter(pk=self.session.pk).update(
            created_at=timezone.now() - dt.timedelta(hours=1))
        self.session.refresh_from_db()
        record, _ = services.sign_in(self.session, self.student, self.session.code)
        self.assertEqual(record.status, RECORD_LATE)

    def test_close_session_marks_missing_absent(self):
        services.sign_in(self.session, self.student, self.session.code)
        services.close_session(self.session, self.teacher)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'closed')
        self.assertEqual(self.session.code, '')

        statuses = dict(AttendanceRecord.objects.filter(
            session=self.session).values_list('record__student_no', 'status'))
        self.assertEqual(statuses['S6001'], RECORD_PRESENT)
        self.assertEqual(statuses['S6002'], RECORD_ABSENT)

    def test_close_session_marks_approved_leave(self):
        services.submit_leave(self.me, LEAVE_PERSONAL,
                              timezone.localdate(), timezone.localdate(),
                              '看病', self.student)
        leave = LeaveRequest.objects.get(record=self.me)
        services.approve_leave(leave, self.teacher)
        services.close_session(self.session, self.teacher)
        self.assertEqual(AttendanceRecord.objects.get(
            session=self.session, record=self.me).status, RECORD_LEAVE)

    def test_teacher_mark_overrides(self):
        services.teacher_mark(self.session, self.me, RECORD_LATE, self.teacher, note='迟到')
        record = AttendanceRecord.objects.get(session=self.session, record=self.me)
        self.assertEqual(record.status, RECORD_LATE)
        self.assertEqual(record.source, 'teacher')

    def test_teacher_mark_other_class_rejected(self):
        outsider = StudentRecord.objects.create(
            student_no='S6098', name='外班2', unit=self.klass2)
        with self.assertRaises(services.AttendanceError) as ctx:
            services.teacher_mark(self.session, outsider, RECORD_PRESENT, self.teacher)
        self.assertEqual(ctx.exception.code, 'NOT_IN_CLASS')


class LeaveTests(AttendanceBase):
    def _leave(self, actor=None, reason='身体不适'):
        return services.submit_leave(
            self.me, LEAVE_PERSONAL, timezone.localdate(),
            timezone.localdate() + dt.timedelta(days=1), reason,
            actor or self.student)

    def test_submit_and_approve(self):
        leave = self._leave()
        self.assertEqual(leave.status, 'submitted')
        services.approve_leave(leave, self.teacher)
        self.assertEqual(leave.status, 'approved')

    def test_self_approval_denied(self):
        leave = self._leave(actor=self.teacher)
        with self.assertRaises(services.AttendanceError) as ctx:
            services.approve_leave(leave, self.teacher)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_empty_reason_rejected(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            self._leave(reason='   ')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_bad_range_rejected(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.submit_leave(
                self.me, LEAVE_PERSONAL, timezone.localdate(),
                timezone.localdate() - dt.timedelta(days=1), '倒序', self.student)
        self.assertEqual(ctx.exception.code, 'BAD_RANGE')

    def test_overlap_rejected_on_approve(self):
        first = self._leave()
        services.approve_leave(first, self.teacher)
        # 直接构造 submitted 记录，模拟"审批期间又出现重叠申请"的防御场景
        second = LeaveRequest.objects.create(
            record=self.me, leave_type=LEAVE_PERSONAL,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + dt.timedelta(days=1),
            reason='再请', submitted_by=str(self.student.pk), status='submitted')
        with self.assertRaises(services.AttendanceError) as ctx:
            services.approve_leave(second, self.teacher)
        self.assertEqual(ctx.exception.code, 'LEAVE_OVERLAP')

    def test_overlapping_submit_rejected(self):
        self._leave()
        with self.assertRaises(services.AttendanceError) as ctx:
            self._leave(reason='重叠再请')
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REQUEST')

    def test_close_leave_requires_finished(self):
        leave = self._leave()
        services.approve_leave(leave, self.teacher)
        with self.assertRaises(services.AttendanceError) as ctx:
            services.close_leave(leave, self.student)
        self.assertEqual(ctx.exception.code, 'NOT_FINISHED')

    def test_close_finished_leave(self):
        past = timezone.localdate() - dt.timedelta(days=3)
        leave = services.submit_leave(
            self.me, LEAVE_PERSONAL, past, past + dt.timedelta(days=1),
            '已结束', self.student)
        services.approve_leave(leave, self.teacher)
        services.close_leave(leave, self.student)
        self.assertEqual(leave.status, 'closed')


class MakeupTests(AttendanceBase):
    def setUp(self):
        super().setUp()
        services.close_session(self.session, self.teacher)
        self.session.refresh_from_db()
        self.makeup = services.submit_makeup(
            self.me, self.session, '签到码输错', self.student)

    def test_submit_makeup(self):
        self.assertEqual(self.makeup.status, 'submitted')

    def test_makeup_requires_closed_session(self):
        new_session = AttendanceSession.objects.create(
            unit=self.klass, session_date=timezone.localdate() + dt.timedelta(days=1),
            period='第3-4节', status='open', code='123456')
        with self.assertRaises(services.AttendanceError) as ctx:
            services.submit_makeup(self.me, new_session, '理由', self.student)
        self.assertEqual(ctx.exception.code, 'SESSION_OPEN')

    def test_duplicate_makeup_rejected(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.submit_makeup(self.me, self.session, '再补', self.student)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REQUEST')

    def test_approve_makeup_overrides_record(self):
        services.approve_makeup(self.makeup, self.teacher)
        record = AttendanceRecord.objects.get(session=self.session, record=self.me)
        self.assertEqual(record.status, RECORD_PRESENT)
        self.assertEqual(record.source, 'makeup')

    def test_self_approval_denied(self):
        makeup = MakeupRequest.objects.create(
            record=self.me, session=self.session, reason='教师自己补',
            submitted_by=str(self.teacher.pk), status='submitted')
        with self.assertRaises(services.AttendanceError) as ctx:
            services.approve_makeup(makeup, self.teacher)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_reject_requires_reason(self):
        with self.assertRaises(services.AttendanceError) as ctx:
            services.reject_makeup(self.makeup, self.teacher, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')


class StatsTests(AttendanceBase):
    def test_unit_stats_rate(self):
        services.sign_in(self.session, self.student, self.session.code)
        services.close_session(self.session, self.teacher)
        rows = services.unit_stats(self.klass)
        by_no = {row['record'].student_no: row for row in rows}
        self.assertEqual(by_no['S6001']['rate'], 100.0)
        self.assertEqual(by_no['S6002']['rate'], 0.0)

    def test_session_stats(self):
        services.sign_in(self.session, self.student, self.session.code)
        stats = services.session_stats(self.session)
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['present'], 1)
        self.assertEqual(stats['rate'], 100.0)
