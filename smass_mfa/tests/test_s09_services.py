"""S09 服务层：TOTP、恢复码、启用/验证与特权判定。

运行::

    python manage.py test smass_mfa.tests.test_s09_services --settings=smass.settings_s09
"""
from __future__ import annotations

import time

from django.test import TestCase, override_settings

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_mfa import services
from smass_mfa.models import MfaDevice, RecoveryCode

PASSWORD = 'S09Svc#2026'

#: RFC 6238 附录 B：secret = ASCII "12345678901234567890"
RFC_SECRET = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class TotpTests(TestCase):
    def test_rfc_vector(self):
        # T=59 → 8 位 94287082；6 位截断为 287082
        self.assertEqual(services.totp(RFC_SECRET, at=59), '287082')

    def test_verify_with_window(self):
        now = time.time()
        code = services.totp(RFC_SECRET, at=now)
        self.assertTrue(services.verify_totp(RFC_SECRET, code, at=now))
        self.assertTrue(services.verify_totp(RFC_SECRET, code, at=now + 30))
        self.assertFalse(services.verify_totp(RFC_SECRET, code, at=now + 150))

    def test_bad_input(self):
        now = time.time()
        self.assertFalse(services.verify_totp(RFC_SECRET, 'abcdef', at=now))
        self.assertFalse(services.verify_totp(RFC_SECRET, '123', at=now))
        self.assertFalse(services.verify_totp(RFC_SECRET, '000000', at=now))


class EnrollmentTests(TestCase):
    def setUp(self):
        self.admin = make_account('s09admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s09stu', [RoleCode.STUDENT])

    def test_enroll_and_confirm(self):
        device, uri = services.enroll(self.admin)
        self.assertEqual(device.status, 'pending')
        self.assertTrue(uri.startswith('otpauth://totp/'))

        codes = services.confirm(self.admin, services.totp(device.secret))
        self.assertEqual(len(codes), services.RECOVERY_CODE_COUNT)
        device.refresh_from_db()
        self.assertEqual(device.status, 'active')
        self.assertIsNotNone(device.confirmed_at)
        self.assertEqual(RecoveryCode.objects.filter(account=self.admin).count(), 8)

    def test_wrong_code_increases_failures(self):
        device, _ = services.enroll(self.admin)
        with self.assertRaises(services.MfaError) as ctx:
            services.confirm(self.admin, '000000')
        self.assertEqual(ctx.exception.code, 'BAD_CODE')
        device.refresh_from_db()
        self.assertEqual(device.failed_attempts, 1)
        self.assertEqual(device.status, 'pending')

    def test_reenroll_active_rejected(self):
        device, _ = services.enroll(self.admin)
        services.confirm(self.admin, services.totp(device.secret))
        with self.assertRaises(services.MfaError) as ctx:
            services.enroll(self.admin)
        self.assertEqual(ctx.exception.code, 'ALREADY_ACTIVE')

    def test_verify_with_recovery_code_once(self):
        device, _ = services.enroll(self.admin)
        codes = services.confirm(self.admin, services.totp(device.secret))

        self.assertEqual(services.verify(self.admin, codes[0]), 'recovery')
        with self.assertRaises(services.MfaError) as ctx:
            services.verify(self.admin, codes[0])
        self.assertEqual(ctx.exception.code, 'BAD_CODE')

    def test_verify_with_totp(self):
        device, _ = services.enroll(self.admin)
        services.confirm(self.admin, services.totp(device.secret))
        self.assertEqual(
            services.verify(self.admin, services.totp(device.secret)), 'totp')

    def test_recovery_codes_stored_hashed(self):
        device, _ = services.enroll(self.admin)
        codes = services.confirm(self.admin, services.totp(device.secret))
        stored = list(RecoveryCode.objects.filter(
            account=self.admin).values_list('code_hash', flat=True))
        self.assertNotIn(codes[0], stored)
        self.assertEqual(len(stored[0]), 64)

    def test_disable_requires_code(self):
        device, _ = services.enroll(self.admin)
        services.confirm(self.admin, services.totp(device.secret))
        with self.assertRaises(services.MfaError) as ctx:
            services.disable(self.admin, '000000')
        self.assertEqual(ctx.exception.code, 'BAD_CODE')

        services.disable(self.admin, services.totp(device.secret))
        device.refresh_from_db()
        self.assertEqual(device.status, 'disabled')

    def test_regenerate_recovery_codes(self):
        device, _ = services.enroll(self.admin)
        first = services.confirm(self.admin, services.totp(device.secret))
        second = services.regenerate_recovery_codes(
            self.admin, services.totp(device.secret))
        self.assertEqual(len(second), services.RECOVERY_CODE_COUNT)
        # 旧码作废
        with self.assertRaises(services.MfaError):
            services.verify(self.admin, first[0])


class PrivilegeTests(TestCase):
    def setUp(self):
        self.admin = make_account('s09p-admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.teacher = make_account('s09p-teacher', [RoleCode.TEACHER],
                                    person_type='teacher')

    def test_privileged_roles(self):
        self.assertTrue(services.is_privileged(self.admin))
        self.assertFalse(services.is_privileged(self.teacher))

    def test_needs_setup(self):
        self.assertTrue(services.needs_setup(self.admin))
        self.assertFalse(services.needs_setup(self.teacher))

        device, _ = services.enroll(self.admin)
        services.confirm(self.admin, services.totp(device.secret))
        self.assertFalse(services.needs_setup(self.admin))

    @override_settings(MFA_ENABLED=False)
    def test_disabled_policy(self):
        self.assertFalse(services.needs_setup(self.admin))

    def test_session_verified(self):
        session = {}
        self.assertFalse(services.session_verified(session))
        services.mark_session_verified(session)
        self.assertTrue(services.session_verified(session))
        services.clear_session_verified(session)
        self.assertFalse(services.session_verified(session))
