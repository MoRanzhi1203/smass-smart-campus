"""G3：审计与 ``django_admin_log`` 解耦、事务语义、脱敏。"""
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase

from r21_account.models import Account, StudentProfile
from r22_account import audit
from r22_account.models import AccountAuditEvent
from r22_account.tests import helpers


class SuccessAuditTests(TestCase):
    def setUp(self):
        self.account = helpers.make_account('T400001')

    def test_success_event_written(self):
        event = audit.record_success(
            'create_profile', actor=self.account, target='student', target_id='S1'
        )
        self.assertEqual(event.outcome, 'success')
        self.assertEqual(event.actor_kind, 'account')
        self.assertEqual(event.actor_login, 'T400001')
        self.assertEqual(event.target, 'student')

    def test_business_and_audit_commit_together(self):
        with audit.business_with_audit(
            'create_profile', actor=self.account, target='student', target_id='S9'
        ):
            StudentProfile.objects.create(
                account=self.account, student_no='S9', name='业务对象'
            )

        self.assertTrue(StudentProfile.objects.filter(student_no='S9').exists())
        self.assertEqual(
            AccountAuditEvent.objects.filter(action='create_profile', outcome='success').count(),
            1,
        )


class FailureAuditTests(TestCase):
    def setUp(self):
        self.account = helpers.make_account('T400002')

    def test_business_failure_rolls_back_but_audit_survives(self):
        before = AccountAuditEvent.objects.count()

        with self.assertRaises(RuntimeError):
            with audit.business_with_audit(
                'failing_business', actor=self.account, target='student', target_id='S10'
            ):
                StudentProfile.objects.create(
                    account=self.account, student_no='S10', name='应回滚'
                )
                raise RuntimeError('boom')

        # 业务回滚
        self.assertFalse(StudentProfile.objects.filter(student_no='S10').exists())

        # 审计留下，且明确是 error，绝不误报 success
        self.assertEqual(AccountAuditEvent.objects.count(), before + 1)
        event = AccountAuditEvent.objects.latest('id')
        self.assertEqual(event.outcome, 'error')
        self.assertEqual(event.context.get('error'), 'RuntimeError')

    def test_denied_event(self):
        event = audit.record_denied('forbidden_action', actor=self.account,
                                    target='route', target_id='/r22/')
        self.assertEqual(event.outcome, 'denied')


class ActorSemanticsTests(TestCase):
    def test_unknown_actor_is_not_fabricated(self):
        event = audit.record_success('anon_probe', actor=None, target='x')
        self.assertEqual(event.actor_kind, 'unknown')
        self.assertEqual(event.actor_login, '')

    def test_legacy_actor_marked_as_legacy(self):
        event = audit.record_success(
            'legacy_probe', actor={'id': 'T5', 'type': 'teacher'}
        )
        self.assertEqual(event.actor_kind, 'legacy')
        self.assertEqual(event.actor_login, 'T5')


class AdminLogDecouplingTests(TestCase):
    """L1：审计绝不能写入 ``django_admin_log``。"""

    def setUp(self):
        self.account = helpers.make_account('T400003')
        helpers.link_legacy(self.account, 'teacher')

    def test_audit_does_not_touch_admin_log_when_pk_collides(self):
        """构造"Account.pk 与某个 auth_user.pk 相同"的最坏情形。"""
        user_model = get_user_model()
        account_pk = self.account.pk

        user_model.objects.create_user(
            username='collide_probe', password='Collide#2024'
        )
        # 让 auth_user 存在同号 id（若自动分配未命中，则直接构造）
        if not user_model.objects.filter(pk=account_pk).exists():
            legacy_user = user_model.objects.first()
            user_model.objects.filter(pk=legacy_user.pk).update(id=account_pk)

        before = LogEntry.objects.count()

        event = audit.record_success(
            'collide_probe', actor=self.account, target='account', target_id=str(account_pk)
        )

        self.assertEqual(LogEntry.objects.count(), before, '审计不得写 django_admin_log')
        self.assertEqual(event.actor_kind, 'account')

    def test_audit_works_when_no_matching_auth_user(self):
        user_model = get_user_model()
        self.assertFalse(user_model.objects.filter(pk=self.account.pk).exists())

        before = LogEntry.objects.count()
        event = audit.record_success('no_user_probe', actor=self.account)

        self.assertEqual(LogEntry.objects.count(), before)
        self.assertIsNotNone(event.pk)

    def test_admin_log_would_fail_for_account_pk(self):
        """反证：若绕过审计直接写 admin log，会因外键不匹配失败。"""
        user_model = get_user_model()
        self.assertFalse(user_model.objects.filter(pk=self.account.pk).exists())

        content_type = ContentType.objects.get_for_model(Account)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LogEntry.objects.log_action(
                    user_id=self.account.pk,
                    content_type_id=content_type.pk,
                    object_id='1',
                    object_repr='probe',
                    action_flag=ADDITION,
                    change_message='probe',
                )


class SanitizationTests(TestCase):
    def test_sensitive_keys_are_removed(self):
        cleaned = audit.sanitize({
            'password': 'plain-text',
            'password_hash': 'pbkdf2_sha256$xxx',
            'token': 'abc',
            'session_key': 'xyz',
            'card_id': '500000199001010011',
            'phone': '13900000000',
            'safe_key': 'keep-me',
        })

        self.assertEqual(cleaned, {'safe_key': 'keep-me'})

    def test_non_dict_context_is_stringified(self):
        cleaned = audit.sanitize(['a', 'b'])
        self.assertEqual(cleaned, {'value': "['a', 'b']"})

    def test_event_context_is_sanitized_at_write(self):
        event = audit.record_success(
            'sanitize_probe', context={'password': 'x', 'ok': 1}
        )
        self.assertEqual(event.context, {'ok': 1})


class AuditToggleTests(TestCase):
    def test_audit_disabled_raises(self):
        from django.test import override_settings

        with override_settings(R22_FLAGS={
            'identity_mode': 'dual', 'route_policy_enabled': True,
            'audit_enabled': False, 'dry_run': False,
        }):
            with self.assertRaises(audit.AuditDisabled):
                audit.record_success('should_not_write')
