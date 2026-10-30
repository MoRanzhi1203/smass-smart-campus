"""S13 服务层：字段分级、最小化导出、披露审批与保留期清理。

运行::

    python manage.py test smass_privacy.tests.test_s13_services --settings=smass.settings_s13
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

from smass_privacy import services
from smass_privacy.models import (
    DataField,
    DisclosureLog,
    DisclosureRequest,
    PrivacySample,
)

PASSWORD = 'S13Svc#2026'
RESOURCE = 'student_record'
PHONE = '13800001234'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class PrivacyBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.record = StudentRecord.objects.create(
            student_no='S13A01', name='赵六', unit=self.klass,
            extra={'phone': PHONE})

        self.admin = make_account('s13admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.admin2 = make_account('s13admin2', [RoleCode.SYSTEM_ADMIN],
                                   person_type='admin')
        self.student = make_account('s13stu', [RoleCode.STUDENT])

        services.set_field(self.admin, RESOURCE, 'student_no', 'public')
        services.set_field(self.admin, RESOURCE, 'name', 'internal')
        services.set_field(self.admin, RESOURCE, 'phone', 'personal', mask='none')


class FieldTests(PrivacyBase):
    def test_student_cannot_configure(self):
        with self.assertRaises(services.PermissionDenied):
            services.set_field(self.student, RESOURCE, 'phone', 'personal')

    def test_bad_classification(self):
        with self.assertRaises(services.PrivacyError) as ctx:
            services.set_field(self.admin, RESOURCE, 'x', 'unknown')
        self.assertEqual(ctx.exception.code, 'BAD_CLASSIFICATION')

    def test_sensitive_forces_partial_mask(self):
        policy = DataField.objects.get(resource=RESOURCE, field='phone')
        self.assertEqual(policy.classification, 'personal')
        self.assertEqual(services.effective_mask(policy), 'partial')

    def test_fields_of(self):
        names = [item.field for item in services.fields_of(RESOURCE)]
        self.assertEqual(names, ['name', 'phone', 'student_no'])


class MinimizeTests(PrivacyBase):
    def test_minimized_rows_only_registered(self):
        names, rows = services.minimized_rows(
            RESOURCE, ['student_no', 'name', 'phone', 'extra_unknown'])
        self.assertEqual(names, ['student_no', 'name', 'phone'])
        row = rows[0]
        self.assertEqual(row['student_no'], 'S13A01')
        self.assertEqual(row['name'], '赵六')
        self.assertEqual(row['phone'], '138****34')
        self.assertNotIn('extra_unknown', row)

    def test_export_digest_deterministic(self):
        request = services.request_disclosure(
            self.student, RESOURCE, ['phone'], '对账')
        text1, rows1, digest1 = services.build_export(request)
        text2, rows2, digest2 = services.build_export(request)
        self.assertEqual(digest1, digest2)
        self.assertEqual(rows1, rows2)
        self.assertIn('138****34', text1)
        self.assertNotIn(PHONE, text1)


class DisclosureTests(PrivacyBase):
    def _request(self):
        return services.request_disclosure(
            self.student, RESOURCE, ['student_no', 'phone'], '统计')

    def test_request_validation(self):
        with self.assertRaises(services.PrivacyError) as ctx:
            services.request_disclosure(self.student, RESOURCE, [], '用途')
        self.assertEqual(ctx.exception.code, 'EMPTY_FIELDS')
        with self.assertRaises(services.PrivacyError) as ctx:
            services.request_disclosure(self.student, RESOURCE, ['nope'], '用途')
        self.assertEqual(ctx.exception.code, 'UNKNOWN_FIELD')
        with self.assertRaises(services.PrivacyError) as ctx:
            services.request_disclosure(self.student, RESOURCE, ['phone'], '  ')
        self.assertEqual(ctx.exception.code, 'EMPTY_PURPOSE')

    def test_self_approval_denied(self):
        request = services.request_disclosure(
            self.admin, RESOURCE, ['phone'], '用途')
        with self.assertRaises(services.PrivacyError) as ctx:
            services.approve_disclosure(request, self.admin)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_student_cannot_approve(self):
        request = self._request()
        with self.assertRaises(services.PermissionDenied):
            services.approve_disclosure(request, self.student)

    def test_full_flow(self):
        request = self._request()
        services.approve_disclosure(request, self.admin)
        request.refresh_from_db()
        self.assertEqual(request.status, 'approved')

        services.execute_disclosure(request, self.student)
        request.refresh_from_db()
        self.assertEqual(request.status, 'executed')
        self.assertGreater(request.row_count, 0)
        self.assertEqual(len(request.output_digest), 64)

        log = DisclosureLog.objects.get(request_id=request.pk)
        self.assertEqual(log.row_count, request.row_count)

    def test_execute_requires_approval(self):
        request = self._request()
        with self.assertRaises(services.PrivacyError) as ctx:
            services.execute_disclosure(request, self.student)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_execute_twice_rejected(self):
        request = self._request()
        services.approve_disclosure(request, self.admin)
        services.execute_disclosure(request, self.student)
        with self.assertRaises(services.PrivacyError) as ctx:
            services.execute_disclosure(request, self.student)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_reject_requires_reason(self):
        request = self._request()
        with self.assertRaises(services.PrivacyError) as ctx:
            services.reject_disclosure(request, self.admin, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_stale_request_expires(self):
        request = self._request()
        DisclosureRequest.objects.filter(pk=request.pk).update(
            created_at=timezone.now() - dt.timedelta(days=2))
        services.expire_stale()
        request.refresh_from_db()
        self.assertEqual(request.status, 'expired')

    def test_scoping(self):
        self._request()
        self.assertEqual(services.scoped_requests(self.student).count(), 1)
        self.assertEqual(services.scoped_requests(self.admin2).count(), 1)
        self.assertEqual(services.scoped_logs(self.student).count(), 0)

    def test_log_append_only(self):
        request = self._request()
        services.approve_disclosure(request, self.admin)
        services.execute_disclosure(request, self.student)
        log = DisclosureLog.objects.first()
        log.digest = 'tampered'
        with self.assertRaises(ValueError):
            log.save()
        with self.assertRaises(ValueError):
            log.delete()


class RetentionTests(PrivacyBase):
    def test_purge_expired_samples(self):
        services.set_field(self.admin, 'sample', 'payload', 'internal',
                           retention_days=30)
        old = PrivacySample.objects.create(resource='sample')
        PrivacySample.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - dt.timedelta(days=31))
        fresh = PrivacySample.objects.create(resource='sample')

        deleted = services.purge_expired()
        self.assertEqual(deleted, 1)
        self.assertFalse(PrivacySample.objects.filter(pk=old.pk).exists())
        self.assertTrue(PrivacySample.objects.filter(pk=fresh.pk).exists())

    def test_no_retention_keeps_data(self):
        services.set_field(self.admin, 'sample', 'payload', 'internal',
                           retention_days=0)
        sample = PrivacySample.objects.create(resource='sample')
        PrivacySample.objects.filter(pk=sample.pk).update(
            created_at=timezone.now() - dt.timedelta(days=365))
        self.assertEqual(services.purge_expired(), 0)
        self.assertTrue(PrivacySample.objects.filter(pk=sample.pk).exists())
