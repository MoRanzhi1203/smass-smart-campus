"""H4：结构化安全告警（可见、可诊断、不含敏感信息）。"""
import logging

from django.test import TestCase

from r22_account import alerts
from r22_account.tests import helpers


class AlertEmissionTests(TestCase):
    def setUp(self):
        alerts.reset_counters()

    def test_identity_conflict_emits_warning(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            alerts.identity_conflict(
                type('I', (), {'kind': 'conflict', 'reason': 'link_mismatch'})(),
                path='/admin/student/list/',
            )

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn('identity_conflict', message)
        self.assertIn('link_mismatch', message)

    def test_alert_contains_no_sensitive_fields(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            alerts.identity_conflict(
                type('I', (), {'kind': 'conflict', 'reason': 'link_mismatch'})(),
                path='/admin/x/',
            )

        message = captured.records[0].getMessage()
        for forbidden in ('password', 'hash', 'token', 'sessionid', 'card_id', 'phone'):
            self.assertNotIn(forbidden, message.lower())

    def test_bulk_auth_failure_threshold_suppresses_noise(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            for _ in range(19):
                alerts.bulk_auth_failure(path='/r21/login/')
            self.assertEqual(len(captured.records), 0)

            alerts.bulk_auth_failure(path='/r21/login/')

        self.assertEqual(len(captured.records), 1)
        self.assertIn('bulk_auth_failure', captured.records[0].getMessage())

    def test_audit_failure_emits_warning(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            alerts.audit_failure(operation='backfill')

        self.assertIn('audit_failure', captured.records[0].getMessage())

    def test_orphan_linkage_alert(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            alerts.orphan_linkage(count=3)

        self.assertIn('orphan_linkage', captured.records[0].getMessage())


class ConflictPathAlertTests(TestCase):
    """真实请求路径：conflict 必须既被拒绝、又产生告警。"""

    def setUp(self):
        alerts.reset_counters()
        self.account = helpers.make_account('H4A001', 'teacher')
        helpers.link_legacy(self.account, 'teacher', 'H4A001')
        helpers.login_account(self.client, 'H4A001')
        helpers.set_legacy_session(self.client, 'teacher', 'OTHER')

    def test_conflict_request_denied_and_alerted(self):
        with self.assertLogs('smass.security', level='WARNING') as captured:
            resp = self.client.get(
                '/legacy-parity/', HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(
            any('identity_conflict' in record.getMessage() for record in captured.records)
        )
