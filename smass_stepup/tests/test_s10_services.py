"""S10 服务层：再认证、双人审批与执行日志。

运行::

    python manage.py test smass_stepup.tests.test_s10_services --settings=smass.settings_s10
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_mfa import services as mfa_services
from smass_stepup import services
from smass_stepup.models import DualApproval, OperationLog, StepUpProof

PASSWORD = 'S10Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class StepUpBase(TestCase):
    def setUp(self):
        self.admin_a = make_account('s10a', [RoleCode.SYSTEM_ADMIN],
                                    person_type='admin')
        self.admin_b = make_account('s10b', [RoleCode.SYSTEM_ADMIN],
                                    person_type='admin')
        self.student = make_account('s10s', [RoleCode.STUDENT])
        self.action = 'reset_other_password'
        self.payload = {'target': 'S001', 'note': '测试'}


class VerifyTests(StepUpBase):
    def test_unknown_action(self):
        with self.assertRaises(services.StepUpError) as ctx:
            services.verify_stepup(self.admin_a, 'nope', PASSWORD)
        self.assertEqual(ctx.exception.code, 'UNKNOWN_ACTION')

    def test_wrong_password(self):
        with self.assertRaises(services.StepUpError) as ctx:
            services.verify_stepup(self.admin_a, self.action, 'wrong')
        self.assertEqual(ctx.exception.code, 'BAD_CODE')
        self.assertFalse(services.has_stepup(self.admin_a, self.action))

    def test_password_proof(self):
        proof = services.verify_stepup(self.admin_a, self.action, PASSWORD)
        self.assertEqual(proof.method, 'password')
        self.assertTrue(services.has_stepup(self.admin_a, self.action))

    def test_proof_expires(self):
        services.verify_stepup(self.admin_a, self.action, PASSWORD)
        StepUpProof.objects.update(
            expires_at=timezone.now() - dt.timedelta(seconds=1))
        self.assertFalse(services.has_stepup(self.admin_a, self.action))

    def test_totp_proof(self):
        device, _ = mfa_services.enroll(self.admin_a)
        mfa_services.confirm(self.admin_a, mfa_services.totp(device.secret))
        proof = services.verify_stepup(
            self.admin_a, self.action,
            mfa_services.totp(device.secret), method='totp')
        self.assertEqual(proof.method, 'totp')


class ApprovalTests(StepUpBase):
    def _proof(self):
        services.verify_stepup(self.admin_a, self.action, PASSWORD)

    def test_open_requires_stepup(self):
        with self.assertRaises(services.StepUpError) as ctx:
            services.open_approval(self.admin_a, self.action, self.payload, '事由')
        self.assertEqual(ctx.exception.code, 'STEPUP_REQUIRED')

    def test_open_requires_reason(self):
        self._proof()
        with self.assertRaises(services.StepUpError) as ctx:
            services.open_approval(self.admin_a, self.action, self.payload, '  ')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_open_and_digest(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        self.assertEqual(approval.status, 'pending')
        self.assertEqual(len(approval.payload_digest), 64)

    def test_self_approval_denied(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        with self.assertRaises(services.StepUpError) as ctx:
            services.approve_approval(approval, self.admin_a)
        self.assertEqual(ctx.exception.code, 'SELF_APPROVAL_DENIED')

    def test_other_admin_approves(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        services.approve_approval(approval, self.admin_b)
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'approved')
        self.assertEqual(approval.approver_id, self.admin_b.pk)

    def test_student_cannot_approve(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        with self.assertRaises(services.PermissionDenied):
            services.approve_approval(approval, self.student)

    def test_execute_writes_log(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        services.approve_approval(approval, self.admin_b)
        services.execute_approval(approval, self.admin_a)

        approval.refresh_from_db()
        self.assertEqual(approval.status, 'executed')
        self.assertIsNotNone(approval.executed_at)
        log = OperationLog.objects.get(approval_id=approval.pk)
        self.assertEqual(log.action_code, self.action)

    def test_execute_twice_rejected(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        services.approve_approval(approval, self.admin_b)
        services.execute_approval(approval, self.admin_a)
        with self.assertRaises(services.StepUpError) as ctx:
            services.execute_approval(approval, self.admin_a)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_execute_before_approval_rejected(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        with self.assertRaises(services.StepUpError) as ctx:
            services.execute_approval(approval, self.admin_a)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_tampered_payload_rejected(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        DualApproval.objects.filter(pk=approval.pk).update(
            payload={'target': 'HACKED'})
        approval.refresh_from_db()
        with self.assertRaises(services.StepUpError) as ctx:
            services.approve_approval(approval, self.admin_b)
        self.assertEqual(ctx.exception.code, 'PAYLOAD_TAMPERED')

    def test_reject_requires_reason(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        with self.assertRaises(services.StepUpError) as ctx:
            services.reject_approval(approval, self.admin_b, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_REASON')

    def test_stale_approval_expires(self):
        self._proof()
        approval = services.open_approval(
            self.admin_a, self.action, self.payload, '事由')
        DualApproval.objects.filter(pk=approval.pk).update(
            created_at=timezone.now() - dt.timedelta(hours=2))
        services.expire_stale()
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'expired')

    def test_scoping(self):
        self._proof()
        services.open_approval(self.admin_a, self.action, self.payload, '事由')
        self.assertEqual(services.scoped_approvals(self.admin_a).count(), 1)
        self.assertEqual(services.scoped_approvals(self.student).count(), 0)
        self.assertGreaterEqual(services.scoped_approvals(self.admin_b).count(), 1)
