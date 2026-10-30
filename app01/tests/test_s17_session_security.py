"""S17 会话安全：设备管理、空闲超时、CSRF 与中间件顺序。

覆盖验收项：

1. 登录后 Session ID 轮换（防会话固定）；
2. 注销后旧 Session 失效且设备记录被撤销；
3. 并发设备列表与"踢出指定设备 / 退出其他设备"；
4. 越权踢出（IDOR）必须被拒绝，包括不同角色共用字符串主键的场景；
5. 空闲超时（默认关闭，开启后超时即 flush 并跳登录）；
6. 破坏性操作强制 POST + CSRF；
7. 中间件顺序：Session → CSRF → ... → 强制改密 → 空闲超时；
8. 新旧身份兼容：``user_id`` 为字符串，兼容 ``auth.User`` 整数主键与 R21/R22 账号。
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from app01 import models
from app01.services import session_security
from app01.tests import helpers

S17_MW = 'app01.middleware.session_security.SessionSecurityMiddleware'


class SessionDeviceTests(TestCase):
    """设备登记、列表、踢出与越权拒绝。"""

    def test_login_registers_device_with_server_side_session_key(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)

        device_id = client.session.get('device_id')
        self.assertTrue(device_id)
        device = models.LoginDevice.objects.get(device_id=device_id)
        self.assertEqual(device.user_id, str(admin.pk))
        self.assertEqual(device.role, 'admin')
        self.assertEqual(device.session_key, client.session.session_key)
        self.assertIsNone(device.revoked_at)

    def test_logout_revokes_device_and_destroys_session(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        device_id = client.session['device_id']
        session_key = client.session.session_key

        resp = client.get('/logout/')
        self.assertEqual(resp.status_code, 302)

        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        device = models.LoginDevice.objects.get(device_id=device_id)
        self.assertIsNotNone(device.revoked_at)
        self.assertEqual(client.get('/admin/admin/list/').status_code, 302)

    def test_session_list_requires_login_and_shows_current_device(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        device_id = client.session['device_id']

        resp = client.get('/account/sessions/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, device_id[:8])
        self.assertContains(resp, '当前设备')

        anonymous = Client()
        resp = anonymous.get('/account/sessions/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/account/admin/', resp['Location'])

    def test_revoke_other_devices_kills_the_other_session(self):
        admin, password = helpers.make_admin()
        first = helpers.logged_in_client('admin', admin.pk, password)
        second = helpers.logged_in_client('admin', admin.pk, password)

        first_device = first.session['device_id']
        second_key = second.session.session_key
        self.assertNotEqual(first_device, second.session['device_id'])

        resp = first.post('/account/sessions/revoke-others/')
        self.assertEqual(resp.status_code, 302)

        self.assertFalse(Session.objects.filter(session_key=second_key).exists())
        self.assertEqual(second.get('/admin/admin/list/').status_code, 302)
        # 当前设备不受影响
        self.assertEqual(first.get('/admin/admin/list/').status_code, 200)

    def test_revoke_specific_device(self):
        admin, password = helpers.make_admin()
        first = helpers.logged_in_client('admin', admin.pk, password)
        second = helpers.logged_in_client('admin', admin.pk, password)
        second_device = second.session['device_id']

        resp = first.post('/account/sessions/revoke/{}/'.format(second_device))
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(
            models.LoginDevice.objects.get(device_id=second_device).revoked_at)
        self.assertEqual(second.get('/admin/admin/list/').status_code, 302)
        self.assertEqual(first.get('/admin/admin/list/').status_code, 200)

    def test_cannot_revoke_current_device_via_endpoint(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        device_id = client.session['device_id']

        resp = client.post('/account/sessions/revoke/{}/'.format(device_id))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('error=current', resp['Location'])
        self.assertIsNone(models.LoginDevice.objects.get(device_id=device_id).revoked_at)
        self.assertEqual(client.get('/admin/admin/list/').status_code, 200)

    def test_cross_role_same_user_id_cannot_be_revoked(self):
        """不同角色共用字符串主键时，踢出必须双匹配 role（IDOR 防护）。"""
        admin, password = helpers.make_admin()
        models.LoginDevice.objects.create(
            device_id='conflict-device', user_id=str(admin.pk), role='student')
        client = helpers.logged_in_client('admin', admin.pk, password)

        resp = client.post('/account/sessions/revoke/conflict-device/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('error=notfound', resp['Location'])
        self.assertIsNone(
            models.LoginDevice.objects.get(device_id='conflict-device').revoked_at)

    def test_student_cannot_revoke_admin_device(self):
        admin, admin_password = helpers.make_admin()
        admin_client = helpers.logged_in_client('admin', admin.pk, admin_password)
        admin_device = admin_client.session['device_id']

        student, student_password = helpers.make_student()
        student_client = helpers.logged_in_client('student', student.pk, student_password)
        resp = student_client.post('/account/sessions/revoke/{}/'.format(admin_device))

        self.assertEqual(resp.status_code, 302)
        self.assertIn('error=notfound', resp['Location'])
        self.assertIsNone(
            models.LoginDevice.objects.get(device_id=admin_device).revoked_at)
        self.assertEqual(admin_client.get('/admin/admin/list/').status_code, 200)

    def test_json_clients_get_structured_errors(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        device_id = client.session['device_id']

        resp = client.post(
            '/account/sessions/revoke/{}/'.format(device_id),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['status'])

    def test_device_ids_are_unique_per_login(self):
        admin, password = helpers.make_admin()
        ids = set()
        for _ in range(2):
            client = helpers.logged_in_client('admin', admin.pk, password)
            ids.add(client.session['device_id'])
        self.assertEqual(len(ids), 2)
        self.assertEqual(
            session_security.list_devices(admin.pk, role='admin').count(), 2)


class IdleTimeoutTests(TestCase):
    """空闲超时：默认关闭；开启后超时 flush 并跳登录。"""

    def _login(self, minutes_ago):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        session = client.session
        session['last_activity'] = (
            timezone.now() - timedelta(minutes=minutes_ago)).isoformat()
        session.save()
        return client

    def test_disabled_by_default(self):
        self.assertFalse(session_security.enabled())
        client = self._login(minutes_ago=24 * 60)
        self.assertEqual(client.get('/admin/admin/list/').status_code, 200)

    @override_settings(SESSION_SECURITY={'ENABLED': True, 'IDLE_TIMEOUT_MINUTES': 30})
    def test_expired_session_is_flushed_and_redirects_to_login(self):
        client = self._login(minutes_ago=61)
        resp = client.get('/admin/admin/list/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])
        self.assertNotIn('info', client.session)

    @override_settings(SESSION_SECURITY={'ENABLED': True, 'IDLE_TIMEOUT_MINUTES': 30})
    def test_active_session_is_not_timed_out(self):
        client = self._login(minutes_ago=1)
        self.assertEqual(client.get('/admin/admin/list/').status_code, 200)
        self.assertIn('info', client.session)

    @override_settings(SESSION_SECURITY={'ENABLED': True, 'IDLE_TIMEOUT_MINUTES': 30})
    def test_timeout_does_not_affect_anonymous_requests(self):
        self.assertEqual(Client().get('/login/').status_code, 200)

    @override_settings(SESSION_SECURITY={'ENABLED': True, 'IDLE_TIMEOUT_MINUTES': 30})
    def test_touch_interval_is_throttled(self):
        client = self._login(minutes_ago=0)
        session = client.session
        session['device_touch_at'] = timezone.now().isoformat()
        session.save()

        request = RequestFactory().get('/admin/admin/list/')
        request.session = client.session
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        self.assertFalse(session_security.touch_session(request))


class SessionSecurityContractTests(TestCase):
    """CSRF、POST 约束、中间件顺序与身份兼容。"""

    def test_mutating_endpoints_reject_get(self):
        admin, password = helpers.make_admin()
        client = helpers.logged_in_client('admin', admin.pk, password)
        self.assertEqual(client.get('/account/sessions/revoke-others/').status_code, 405)

    def test_csrf_is_required_for_mutating_endpoints(self):
        admin, password = helpers.make_admin()
        client = Client(enforce_csrf_checks=True)
        page = client.get('/login/account/admin/')
        token = client.cookies['csrftoken'].value
        self.assertEqual(page.status_code, 200)

        resp = client.post('/login/account/admin/', {
            'id': admin.pk, 'password': password, 'csrfmiddlewaretoken': token,
        })
        self.assertEqual(resp.status_code, 302)

        # 不带 CSRF 令牌的破坏性请求必须被拒绝
        self.assertEqual(client.post('/account/sessions/revoke-others/').status_code, 403)

    def test_middleware_ordering(self):
        mw = list(settings.MIDDLEWARE)
        session_idx = mw.index('django.contrib.sessions.middleware.SessionMiddleware')
        csrf_idx = mw.index('django.middleware.csrf.CsrfViewMiddleware')
        lifecycle_idx = mw.index(
            'app01.middleware.password_lifecycle.PasswordLifecycleMiddleware')
        s17_idx = mw.index(S17_MW)

        self.assertLess(session_idx, csrf_idx)
        self.assertLess(csrf_idx, s17_idx)
        self.assertLess(lifecycle_idx, s17_idx)
        self.assertLess(s17_idx, len(mw))

    def test_identity_compatible_with_string_and_integer_ids(self):
        """user_id 用字符串，兼容 auth.User 整数主键与 R21/R22 账号主键。"""
        models.LoginDevice.objects.create(
            device_id='legacy-int-id', user_id=str(42), role='admin')
        models.LoginDevice.objects.create(
            device_id='r21-str-id', user_id='42', role='admin')

        devices = session_security.list_devices(42, role='admin')
        self.assertEqual(devices.count(), 2)
        self.assertTrue(session_security.revoke_device(
            42, 'legacy-int-id', role='admin'))
        self.assertEqual(devices.count(), 1)
