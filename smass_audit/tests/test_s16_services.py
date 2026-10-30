"""S16 服务层：哈希链、篡改检测、告警与权限。

运行::

    python manage.py test smass_audit.tests.test_s16_services --settings=smass.settings_s16
"""
from __future__ import annotations

from django.test import TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_audit import services
from smass_audit.models import AuditEvent, SecurityAlert

PASSWORD = 'S16Svc#2026'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ChainTests(TestCase):
    def setUp(self):
        self.admin = make_account('s16admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s16stu', [RoleCode.STUDENT])

    def test_chain_links(self):
        first = services.record(self.student, 'login', result='success')
        second = services.record(self.student, 'view', result='success')
        self.assertTrue(first.hash)
        self.assertEqual(second.prev_hash, first.hash)
        self.assertTrue(services.verify_chain()['ok'])

    def test_tamper_detected(self):
        first = services.record(self.student, 'login')
        services.record(self.student, 'view')
        AuditEvent.objects.filter(pk=first.pk).update(action='tampered')
        result = services.verify_chain()
        self.assertFalse(result['ok'])
        self.assertEqual(result['broken_at'], first.pk)

    def test_append_only(self):
        event = services.record(self.student, 'login')
        event.action = 'tampered'
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()

    def test_bad_input(self):
        with self.assertRaises(services.AuditError) as ctx:
            services.record(self.student, '')
        self.assertEqual(ctx.exception.code, 'EMPTY_ACTION')
        with self.assertRaises(services.AuditError) as ctx:
            services.record(self.student, 'x', result='unknown')
        self.assertEqual(ctx.exception.code, 'BAD_RESULT')


class AlertTests(TestCase):
    def setUp(self):
        self.admin = make_account('s16alert-admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s16alert-stu', [RoleCode.STUDENT])

    def _denied(self, count, actor=None):
        for _ in range(count):
            services.record(actor or self.student, 'forbidden_action',
                            result='denied', reason='PERMISSION_DENIED')

    def test_below_threshold_no_alert(self):
        self._denied(2)
        self.assertEqual(services.detect_alerts(), 0)
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_threshold_creates_alert(self):
        self._denied(5)
        self.assertEqual(services.detect_alerts(), 1)
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.alert_type, 'denied_burst')
        self.assertEqual(alert.status, 'open')
        self.assertEqual(alert.detail['count'], 5)

    def test_alert_is_idempotent_in_window(self):
        self._denied(6)
        self.assertEqual(services.detect_alerts(), 1)
        self.assertEqual(services.detect_alerts(), 0)
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_acknowledge(self):
        self._denied(5)
        services.detect_alerts()
        alert = SecurityAlert.objects.get()
        services.acknowledge_alert(alert, self.admin)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'acknowledged')
        self.assertEqual(alert.acknowledged_by, str(self.admin.pk))

        with self.assertRaises(services.AuditError) as ctx:
            services.acknowledge_alert(alert, self.admin)
        self.assertEqual(ctx.exception.code, 'BAD_STATE')

    def test_student_cannot_acknowledge(self):
        self._denied(5)
        services.detect_alerts()
        alert = SecurityAlert.objects.get()
        with self.assertRaises(services.PermissionDenied):
            services.acknowledge_alert(alert, self.student)


class ScopingTests(TestCase):
    def setUp(self):
        self.admin = make_account('s16scope-admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s16scope-stu', [RoleCode.STUDENT])
        self.other = make_account('s16scope-other', [RoleCode.STUDENT])
        services.record(self.student, 'action_a')
        services.record(self.other, 'action_b')

    def test_student_sees_own_events(self):
        events = list(services.scoped_events(self.student))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, 'action_a')

    def test_admin_sees_all_events(self):
        self.assertEqual(len(list(services.scoped_events(self.admin))), 2)

    def test_student_cannot_see_alerts(self):
        self.assertEqual(services.scoped_alerts(self.student).count(), 0)
        self.assertGreaterEqual(services.scoped_alerts(self.admin).count(), 0)

    def test_stats_chain_ok(self):
        stats = services.stats(self.admin)
        self.assertEqual(stats['events'], 2)
        self.assertTrue(stats['chain']['ok'])
