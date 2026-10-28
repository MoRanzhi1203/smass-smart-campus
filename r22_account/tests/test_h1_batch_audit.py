"""H1：批次级审计与回滚可追溯。"""
from django.test import TestCase, override_settings

from app01 import models as legacy
from r21_account.models import Account, LegacyAccountLink, StudentProfile
from r22_account import batch_audit
from r22_account.models import AccountAuditEvent

PASSWORD = 'H1Pass#2024'


class H1Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.hashers import make_password

        hashed = make_password(PASSWORD)
        cls.college = legacy.College.objects.create(name='信息工程学院')
        cls.grade = legacy.Grade.objects.create(name='2021级')
        cls.major = legacy.Major.objects.create(college=cls.college, name='信息安全技术')
        cls.classes = legacy.Classes.objects.create(
            name='信安2101', grade=cls.grade, major=cls.major
        )
        legacy.Admin.objects.create(id='001', name='管理员', password=hashed)
        legacy.Teacher.objects.create(
            id='T01', name='教师甲', password=hashed, pinyin='jsj', sex=0,
            nation=None, cardID='', phone='', qq='', address='',
            entry_time=None, college=cls.college, political=0,
        )
        legacy.Student.objects.create(
            id='S01', name='学生甲', password=hashed, pinyin='xsj', sex=0,
            nation=None, classes=cls.classes, cardID='', phone=None, qq=None,
            address=None, building=None, dormitory=None, political=0,
        )


class BackfillBatchTests(H1Fixture):
    def test_backfill_creates_batch_event(self):
        batch_id, output, outcome = batch_audit.run_backfill()

        self.assertTrue(batch_id)
        self.assertIn('created=3', output)
        self.assertEqual(outcome, 'success')

        event = AccountAuditEvent.objects.get(batch_id=batch_id)
        self.assertEqual(event.operation, 'backfill')
        self.assertEqual(event.outcome, 'success')
        self.assertEqual(event.actor_kind, 'system')
        self.assertEqual(event.counts.get('accounts'), 3)
        self.assertEqual(event.counts.get('links'), 3)

    def test_counts_contain_no_sensitive_fields(self):
        batch_id, _, _ = batch_audit.run_backfill()
        event = AccountAuditEvent.objects.get(batch_id=batch_id)

        keys = set(event.counts.keys())
        for forbidden in ('password', 'hash', 'token', 'name', 'card_id'):
            self.assertNotIn(forbidden, keys)
        self.assertTrue(all(isinstance(v, (int, bool)) for v in event.counts.values()))

    def test_idempotent_backfill_is_recorded_separately(self):
        first, _, _ = batch_audit.run_backfill()
        second, output, _ = batch_audit.run_backfill()

        self.assertNotEqual(first, second)
        self.assertIn('created=0', output)
        self.assertEqual(Account.objects.count(), 3)

        second_event = AccountAuditEvent.objects.get(batch_id=second)
        self.assertEqual(second_event.counts.get('accounts'), 0)


class RollbackBatchTests(H1Fixture):
    def test_rollback_appends_event_linked_to_source_batch(self):
        backfill_batch, _, _ = batch_audit.run_backfill()
        rollback_batch, _, _ = batch_audit.run_rollback()

        self.assertNotEqual(backfill_batch, rollback_batch)

        rollback_event = AccountAuditEvent.objects.get(batch_id=rollback_batch)
        self.assertEqual(rollback_event.operation, 'rollback')
        self.assertEqual(rollback_event.source_batch_id, backfill_batch)
        self.assertEqual(rollback_event.counts.get('accounts'), -3)

        # 历史不被删除
        self.assertTrue(AccountAuditEvent.objects.filter(batch_id=backfill_batch).exists())

    def test_repeated_rollback_creates_new_batches_without_erasing_history(self):
        batch_audit.run_backfill()
        first_rollback, _, _ = batch_audit.run_rollback()
        second_rollback, _, _ = batch_audit.run_rollback()

        self.assertNotEqual(first_rollback, second_rollback)
        self.assertEqual(AccountAuditEvent.objects.filter(operation='rollback').count(), 2)
        # 第二次回滚没有可删对象
        self.assertEqual(
            AccountAuditEvent.objects.get(batch_id=second_rollback).counts.get('accounts'), 0
        )

    def test_batch_chain_is_traceable(self):
        backfill_batch, _, _ = batch_audit.run_backfill()
        rollback_batch, _, _ = batch_audit.run_rollback()

        chain = batch_audit.batch_chain()
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0][0], 'backfill')
        self.assertEqual(chain[1][0], 'rollback')
        self.assertEqual(chain[1][2], backfill_batch)
        self.assertEqual(chain[1][1], rollback_batch)

    def test_preexisting_account_survives_rollback_and_is_not_audited_as_backfilled(self):
        batch_audit.run_backfill()
        survivor = Account.objects.create_user(
            'PREEXIST_H1', PASSWORD, display_name='预存', person_type='teacher'
        )
        survivor.must_change_password = False
        survivor.save(update_fields=['must_change_password'])

        rollback_batch, _, _ = batch_audit.run_rollback()

        self.assertTrue(Account.objects.filter(login_name='PREEXIST_H1').exists())
        self.assertEqual(AccountAuditEvent.objects.get(batch_id=rollback_batch)
                         .counts.get('accounts'), -3)


class ReconciliationTests(H1Fixture):
    def test_unbatched_backfill_detected(self):
        """有映射但没有任何批次事件 → 提示崩溃窗口。"""
        batch_audit.run_backfill()
        AccountAuditEvent.objects.filter(action='batch_executed').delete()

        self.assertTrue(batch_audit.find_unbatched_backfill(window_minutes=60))

    def test_batched_backfill_not_flagged(self):
        batch_audit.run_backfill()
        self.assertFalse(batch_audit.find_unbatched_backfill(window_minutes=60))

    def test_no_links_no_warning(self):
        self.assertFalse(batch_audit.find_unbatched_backfill())


class AuditDisabledBehaviourTests(H1Fixture):
    @override_settings(R22_FLAGS={
        'identity_mode': 'dual', 'route_policy_enabled': True,
        'audit_enabled': False, 'dry_run': False,
    })
    def test_backfill_raises_when_audit_disabled(self):
        from r22_account.audit import AuditDisabled

        with self.assertRaises(AuditDisabled):
            batch_audit.run_backfill()
        # 业务已执行但审计被禁 → 明确异常，而不是静默无审计
        self.assertEqual(Account.objects.count(), 3)
