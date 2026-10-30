"""S11 服务层：字段策略判定、脱敏与决策审计。

运行::

    python manage.py test smass_policy.tests.test_s11_services --settings=smass.settings_s11
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

from smass_policy import services
from smass_policy.models import FieldPolicy, PolicyDecisionLog

PASSWORD = 'S11Svc#2026'
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


class PolicyBase(TestCase):
    def setUp(self):
        self.college = OrganizationUnit.objects.create(
            code='C01', name='学院', unit_type=UNIT_TYPE_COLLEGE)
        self.major = OrganizationUnit.objects.create(
            code='M01', name='专业', unit_type=UNIT_TYPE_MAJOR, parent=self.college)
        self.klass = OrganizationUnit.objects.create(
            code='CL01', name='一班', unit_type=UNIT_TYPE_CLASS, parent=self.major)
        self.record = StudentRecord.objects.create(
            student_no='S11A01', name='张三', unit=self.klass, status='enrolled',
            extra={'phone': PHONE, 'id_card': '110101199001011234'})

        self.admin = make_account('s11admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('s11teacher', [RoleCode.TEACHER],
                                    person_type='teacher')
        self.student = make_account('s11stu', [RoleCode.STUDENT])


class ReadPolicyTests(PolicyBase):
    def test_default_deny_without_policy(self):
        result = services.read_field(self.student, RESOURCE, 'phone', self.record)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'NO_POLICY')
        self.assertIsNone(result['value'])

    def test_role_allowed(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher,system_admin')
        result = services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['value'], PHONE)
        self.assertFalse(result['masked'])

    def test_role_denied(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='system_admin')
        result = services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'ROLE_DENIED')

    def test_condition_allows_and_denies(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher',
                            condition={'status': ['enrolled']})
        self.assertTrue(services.read_field(
            self.teacher, RESOURCE, 'phone', self.record)['allowed'])

        StudentRecord.objects.filter(pk=self.record.pk).update(status='suspended')
        self.record.refresh_from_db()
        result = services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'CONDITION_DENIED')

    def test_partial_mask(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher', mask='partial')
        result = services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        self.assertTrue(result['allowed'])
        self.assertTrue(result['masked'])
        self.assertEqual(result['value'], '138****34')
        self.assertNotIn('0000', result['value'])

    def test_full_mask(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher', mask='full')
        result = services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        self.assertEqual(result['value'], '***')

    def test_disabled_policy_denies(self):
        policy = services.set_policy(self.admin, RESOURCE, 'phone',
                                     read_roles='teacher')
        services.disable_policy(self.admin, policy)
        self.assertFalse(services.read_field(
            self.teacher, RESOURCE, 'phone', self.record)['allowed'])


class WritePolicyTests(PolicyBase):
    def test_write_denied_by_default(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher', write_roles='')
        self.assertFalse(services.can_write(
            self.teacher, RESOURCE, 'phone', self.record))

    def test_write_allowed(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher', write_roles='system_admin')
        self.assertTrue(services.can_write(
            self.admin, RESOURCE, 'phone', self.record))
        self.assertFalse(services.can_write(
            self.teacher, RESOURCE, 'phone', self.record))


class EffectiveFieldsTests(PolicyBase):
    def test_effective_fields(self):
        services.set_policy(self.admin, RESOURCE, 'phone',
                            read_roles='teacher', mask='partial')
        services.set_policy(self.admin, RESOURCE, 'name',
                            read_roles='student,teacher')
        fields = services.effective_fields(self.teacher, RESOURCE, self.record)
        self.assertEqual(set(fields), {'phone', 'name'})
        self.assertTrue(fields['phone']['read'])
        self.assertEqual(fields['phone']['mask'], 'partial')
        self.assertFalse(fields['phone']['write'])

        student_fields = services.effective_fields(
            self.student, RESOURCE, self.record)
        self.assertFalse(student_fields['phone']['read'])
        self.assertTrue(student_fields['name']['read'])


class ConfigAndAuditTests(PolicyBase):
    def test_student_cannot_configure(self):
        with self.assertRaises(services.PermissionDenied):
            services.set_policy(self.student, RESOURCE, 'phone',
                                read_roles='student')

    def test_empty_field_rejected(self):
        with self.assertRaises(services.PolicyError) as ctx:
            services.set_policy(self.admin, RESOURCE, '  ')
        self.assertEqual(ctx.exception.code, 'EMPTY_FIELD')

    def test_bad_mask_rejected(self):
        with self.assertRaises(services.PolicyError) as ctx:
            services.set_policy(self.admin, RESOURCE, 'phone', mask='weird')
        self.assertEqual(ctx.exception.code, 'BAD_MASK')

    def test_policy_upsert(self):
        services.set_policy(self.admin, RESOURCE, 'phone', read_roles='teacher')
        services.set_policy(self.admin, RESOURCE, 'phone', read_roles='system_admin')
        self.assertEqual(FieldPolicy.objects.filter(
            resource=RESOURCE, field='phone').count(), 1)
        self.assertFalse(services.read_field(
            self.teacher, RESOURCE, 'phone', self.record)['allowed'])

    def test_decision_log_written(self):
        services.set_policy(self.admin, RESOURCE, 'phone', read_roles='teacher')
        services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        services.read_field(self.student, RESOURCE, 'phone', self.record)
        logs = PolicyDecisionLog.objects.all()
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.filter(allowed=True).count(), 1)
        self.assertEqual(logs.filter(allowed=False).count(), 1)

    def test_decision_log_append_only(self):
        services.set_policy(self.admin, RESOURCE, 'phone', read_roles='teacher')
        services.read_field(self.teacher, RESOURCE, 'phone', self.record)
        log = PolicyDecisionLog.objects.first()
        log.reason = 'tampered'
        with self.assertRaises(ValueError):
            log.save()
        with self.assertRaises(ValueError):
            log.delete()

    def test_logs_scoping(self):
        self.assertEqual(services.decision_logs(self.student).count(), 0)
