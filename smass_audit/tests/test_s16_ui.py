"""S16 页面层：审计事件、链状态、告警扫描与确认。

运行::

    python manage.py test smass_audit.tests.test_s16_ui --settings=smass.settings_s16
"""
from __future__ import annotations

from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_audit import services
from smass_audit.models import SecurityAlert

PASSWORD = 'S16Ui#2026'
LOGIN = '/r21/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


class AuditUiTests(TestCase):
    def setUp(self):
        self.admin = make_account('s16uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s16uistu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s16/events/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden_on_alerts(self):
        login(self.client, 's16uistu')
        self.assertEqual(403, self.client.get('/s16/alerts/').status_code)

    def test_student_sees_own_events_only(self):
        services.record(self.student, 'own_action')
        services.record(self.admin, 'admin_action')
        login(self.client, 's16uistu')
        response = self.client.get('/s16/events/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'own_action')
        self.assertNotContains(response, 'admin_action')

    def test_admin_sees_chain_status(self):
        services.record(self.student, 'login')
        login(self.client, 's16uiadmin')
        response = self.client.get('/s16/events/')
        self.assertContains(response, '哈希链')
        self.assertContains(response, '完整')

    def test_scan_creates_alert_and_ack(self):
        for _ in range(5):
            services.record(self.student, 'denied_action', result='denied')

        admin = Client()
        login(admin, 's16uiadmin')
        response = admin.post('/s16/alerts/scan/')
        self.assertEqual(302, response.status_code)
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.status, 'open')

        response = admin.post('/s16/alerts/{}/ack/'.format(alert.pk))
        self.assertEqual(302, response.status_code)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'acknowledged')

    def test_student_cannot_ack(self):
        for _ in range(5):
            services.record(self.student, 'denied_action', result='denied')
        services.detect_alerts()
        alert = SecurityAlert.objects.get()

        login(self.client, 's16uistu')
        response = self.client.post('/s16/alerts/{}/ack/'.format(alert.pk))
        self.assertEqual(403, response.status_code)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')
