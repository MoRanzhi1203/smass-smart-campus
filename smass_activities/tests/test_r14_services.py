"""R14 服务层：活动发布、报名候补、签到、关闭与学分认定。

运行::

    python manage.py test smass_activities.tests.test_r14_services --settings=smass.settings_r14
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

from smass_activities import services
from smass_activities.models import (
    Activity,
    ActivityCredit,
    ActivityRegistration,
)

PASSWORD = 'R14Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ActivityBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)

        self.teacher = make_account('r14teacher', [RoleCode.TEACHER], person_type='teacher')
        self.admin = make_account('r14admin', [RoleCode.SYSTEM_ADMIN], person_type='admin')
        self.student = make_account('r14stu', [RoleCode.STUDENT])
        self.student2 = make_account('r14stu2', [RoleCode.STUDENT])

        self.me = StudentRecord.objects.create(
            student_no='S7101', name='活动学生', unit=self.klass, account=self.student)
        self.other = StudentRecord.objects.create(
            student_no='S7102', name='活动学生二', unit=self.klass, account=self.student2)

        now = timezone.now()
        self.activity = services.create_activity(
            self.teacher, '志愿清扫', 'volunteer',
            now + dt.timedelta(hours=1), now + dt.timedelta(hours=3),
            capacity=1, credit_points=1, volunteer_hours=2, location='操场')
        services.publish_activity(self.activity, self.teacher)
        self.activity.refresh_from_db()


class ActivityTests(ActivityBase):
    def test_create_and_publish(self):
        self.assertEqual(self.activity.status, 'published')
        self.assertEqual(len(self.activity.checkin_code), 6)
        self.assertEqual(self.activity.credit_points, 1)

    def test_student_cannot_create(self):
        now = timezone.now()
        with self.assertRaises(services.PermissionDenied):
            services.create_activity(
                self.student, '非法活动', 'club',
                now + dt.timedelta(hours=1), now + dt.timedelta(hours=2))

    def test_bad_time_range(self):
        now = timezone.now()
        with self.assertRaises(services.ActivityError) as ctx:
            services.create_activity(
                self.teacher, '倒序', 'lecture',
                now + dt.timedelta(hours=2), now + dt.timedelta(hours=1))
        self.assertEqual(ctx.exception.code, 'BAD_RANGE')

    def test_publish_twice_rejected(self):
        with self.assertRaises(services.ActivityError) as ctx:
            services.publish_activity(self.activity, self.teacher)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')


class RegistrationTests(ActivityBase):
    def test_register_and_capacity_waitlist(self):
        first = services.register(self.activity, self.me, self.student)
        self.assertEqual(first.status, 'registered')

        second = services.register(self.activity, self.other, self.student2)
        self.assertEqual(second.status, 'waitlisted')

    def test_duplicate_registration_rejected(self):
        services.register(self.activity, self.me, self.student)
        with self.assertRaises(services.ActivityError) as ctx:
            services.register(self.activity, self.me, self.student)
        self.assertEqual(ctx.exception.code, 'DUPLICATE_REGISTRATION')

    def test_cancel_promotes_waitlist(self):
        first = services.register(self.activity, self.me, self.student)
        second = services.register(self.activity, self.other, self.student2)
        self.assertEqual(second.status, 'waitlisted')

        services.cancel_registration(first, self.student)
        second.refresh_from_db()
        self.assertEqual(second.status, 'registered')

    def test_cancel_then_register_again(self):
        first = services.register(self.activity, self.me, self.student)
        services.cancel_registration(first, self.student)
        again = services.register(self.activity, self.me, self.student)
        self.assertEqual(again.status, 'registered')

    def test_cannot_register_unpublished(self):
        now = timezone.now()
        draft = services.create_activity(
            self.teacher, '草稿活动', 'lecture',
            now + dt.timedelta(hours=1), now + dt.timedelta(hours=2))
        with self.assertRaises(services.ActivityError) as ctx:
            services.register(draft, self.me, self.student)
        self.assertEqual(ctx.exception.code, 'NOT_PUBLISHED')

    def test_cannot_register_after_start(self):
        Activity.objects.filter(pk=self.activity.pk).update(
            start_at=timezone.now() - dt.timedelta(minutes=1))
        self.activity.refresh_from_db()
        with self.assertRaises(services.ActivityError) as ctx:
            services.register(self.activity, self.me, self.student)
        self.assertEqual(ctx.exception.code, 'ACTIVITY_STARTED')


class CheckInTests(ActivityBase):
    def setUp(self):
        super().setUp()
        self.registration = services.register(self.activity, self.me, self.student)
        Activity.objects.filter(pk=self.activity.pk).update(
            start_at=timezone.now() - dt.timedelta(minutes=10),
            end_at=timezone.now() + dt.timedelta(hours=1))
        self.activity.refresh_from_db()
        self.registration = ActivityRegistration.objects.select_related(
            'activity').get(pk=self.registration.pk)

    def test_check_in_success(self):
        services.check_in(self.registration, self.student, self.activity.checkin_code)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, 'checked_in')

    def test_wrong_code(self):
        with self.assertRaises(services.ActivityError) as ctx:
            services.check_in(self.registration, self.student, '000000')
        self.assertEqual(ctx.exception.code, 'BAD_CODE')

    def test_out_of_window(self):
        Activity.objects.filter(pk=self.activity.pk).update(
            start_at=timezone.now() + dt.timedelta(hours=5),
            end_at=timezone.now() + dt.timedelta(hours=6))
        self.activity.refresh_from_db()
        with self.assertRaises(services.ActivityError) as ctx:
            services.check_in(self.registration, self.student,
                              self.activity.checkin_code)
        self.assertEqual(ctx.exception.code, 'OUT_OF_WINDOW')

    def test_other_cannot_check_in(self):
        with self.assertRaises(services.PermissionDenied):
            services.check_in(self.registration, self.student2,
                              self.activity.checkin_code)


class CloseAndCreditTests(ActivityBase):
    def setUp(self):
        super().setUp()
        self.registration = services.register(self.activity, self.me, self.student)
        Activity.objects.filter(pk=self.activity.pk).update(
            start_at=timezone.now() - dt.timedelta(minutes=10),
            end_at=timezone.now() + dt.timedelta(hours=1))
        self.activity.refresh_from_db()
        self.registration = ActivityRegistration.objects.select_related(
            'activity').get(pk=self.registration.pk)

    def test_close_marks_absent(self):
        services.close_activity(self.activity, self.teacher)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, 'absent')
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.checkin_code, '')

    def test_generate_and_approve_credit(self):
        services.check_in(self.registration, self.student, self.activity.checkin_code)
        services.close_activity(self.activity, self.teacher)
        count = services.generate_credits(self.activity, self.teacher)
        self.assertEqual(count, 1)

        credit = ActivityCredit.objects.get(activity=self.activity)
        self.assertEqual(credit.status, 'pending')
        services.approve_credit(credit, self.admin)
        credit.refresh_from_db()
        self.assertEqual(credit.status, 'approved')

        summary = services.credit_summary(self.me)
        self.assertEqual(summary['points'], 1)
        self.assertEqual(summary['hours'], 2)

    def test_generate_is_idempotent(self):
        services.check_in(self.registration, self.student, self.activity.checkin_code)
        services.close_activity(self.activity, self.teacher)
        services.generate_credits(self.activity, self.teacher)
        services.generate_credits(self.activity, self.teacher)
        self.assertEqual(ActivityCredit.objects.filter(activity=self.activity).count(), 1)

    def test_organizer_cannot_approve_own_credit(self):
        services.check_in(self.registration, self.student, self.activity.checkin_code)
        services.close_activity(self.activity, self.teacher)
        services.generate_credits(self.activity, self.teacher)
        credit = ActivityCredit.objects.get(activity=self.activity)
        with self.assertRaises(services.ActivityError) as ctx:
            services.approve_credit(credit, self.teacher)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_reject_requires_reason(self):
        services.check_in(self.registration, self.student, self.activity.checkin_code)
        services.close_activity(self.activity, self.teacher)
        services.generate_credits(self.activity, self.teacher)
        credit = ActivityCredit.objects.get(activity=self.activity)
        with self.assertRaises(services.ActivityError) as ctx:
            services.reject_credit(credit, self.admin, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')
