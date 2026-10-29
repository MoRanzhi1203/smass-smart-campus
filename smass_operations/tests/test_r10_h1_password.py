"""H1：R10 隔离配置下的真实密码生命周期。

修复点：`urls_r10` 曾用 `RedirectView` 占位，等于禁用强制改密。
本文件验证 `smass.settings_r10` 下的真实行为。
"""
from django.contrib.auth import authenticate
from django.test import Client, TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode

PASSWORD = 'H1Init#2024'
NEW_PASSWORD = 'H1Changed#2024'


def make_account(login, role, must_change=False):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin'
    )
    account.must_change_password = must_change
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='h1')
    return Account.objects.get(pk=account.pk)


class ChangePasswordRoutingTests(TestCase):
    """路由不再重定向占位。"""

    def setUp(self):
        self.account = make_account('H1ADM', RoleCode.SYSTEM_ADMIN)
        self.client.force_login(self.account)

    def test_get_renders_real_form(self):
        resp = self.client.get('/r21/change-password/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        # 真实表单字段，而非重定向
        self.assertIn('name="current_password"', body)
        self.assertIn('name="new_password"', body)
        self.assertIn('name="confirm_password"', body)

    def test_no_longer_redirects(self):
        resp = self.client.get('/r21/change-password/')
        self.assertNotIn(resp.status_code, (301, 302))

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get('/r21/change-password/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/r21/login/', resp['Location'])


class ForcedChangeTests(TestCase):
    """首次登录（must_change_password=True）被强制改密。"""

    def setUp(self):
        self.account = make_account('H1FORCE', RoleCode.SYSTEM_ADMIN, must_change=True)
        self.client.force_login(self.account)

    def test_other_pages_redirect_to_change_password(self):
        for url in ('/r10/', '/r4/units/', '/r7/dashboard/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/r21/change-password/', resp['Location'], url)

    def test_ajax_gets_403_json(self):
        resp = self.client.get('/r4/units/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        payload = resp.json()
        self.assertEqual(payload['code'], 'must_change_password')
        self.assertIn('首次登录', payload['tips'])

    def test_change_page_itself_allowed(self):
        self.assertEqual(
            self.client.get('/r21/change-password/').status_code, 200)

    def test_logout_allowed_while_forced(self):
        self.assertEqual(self.client.get('/r21/logout/').status_code, 302)

    def test_change_then_redirect_target_reachable(self):
        resp = self.client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)

        self.account.refresh_from_db()
        self.assertFalse(self.account.must_change_password)

        # 强制解除后可访问业务页
        self.assertEqual(self.client.get('/r4/units/').status_code, 200)


class ValidationTests(TestCase):
    """错误路径必须拒绝且不写库。"""

    def setUp(self):
        self.account = make_account('H1VAL', RoleCode.SYSTEM_ADMIN)
        self.client.force_login(self.account)

    def _post(self, current, new, confirm):
        return self.client.post('/r21/change-password/', {
            'current_password': current,
            'new_password': new,
            'confirm_password': confirm,
        })

    def test_wrong_current_password_rejected(self):
        resp = self._post('wrong', NEW_PASSWORD, NEW_PASSWORD)
        self.assertContains(resp, '当前密码不正确')
        self.assertTrue(authenticate(username='H1VAL', password=PASSWORD))

    def test_mismatch_rejected(self):
        resp = self._post(PASSWORD, NEW_PASSWORD, 'Different#2024')
        self.assertContains(resp, '不一致')
        self.assertTrue(authenticate(username='H1VAL', password=PASSWORD))

    def test_same_as_current_rejected(self):
        resp = self._post(PASSWORD, PASSWORD, PASSWORD)
        self.assertContains(resp, '不能与当前密码相同')

    def test_weak_password_rejected(self):
        """行为断言：弱密码不得改变存储的哈希（不依赖错误文案语言）。"""
        old_hash = Account.objects.get(pk=self.account.pk).password

        resp = self._post(PASSWORD, '123', '123')
        self.assertEqual(resp.status_code, 200)

        new_hash = Account.objects.get(pk=self.account.pk).password
        self.assertEqual(old_hash, new_hash, '弱密码被接受了（哈希被改写）')
        self.assertTrue(authenticate(username='H1VAL', password=PASSWORD))
        self.assertFalse(authenticate(username='H1VAL', password='123'))

    def test_short_password_rejected_by_length_validator(self):
        """明确验证长度验证器生效（>=8 字符）。"""
        old_hash = Account.objects.get(pk=self.account.pk).password
        self._post(PASSWORD, 'Ab1!', 'Ab1!')
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).password, old_hash)

    def test_successful_change_updates_hash(self):
        old_hash = Account.objects.get(pk=self.account.pk).password
        self._post(PASSWORD, NEW_PASSWORD, NEW_PASSWORD)

        new_hash = Account.objects.get(pk=self.account.pk).password
        self.assertNotEqual(old_hash, new_hash, '密码哈希未变化')
        self.assertTrue(authenticate(username='H1VAL', password=NEW_PASSWORD))
        self.assertFalse(authenticate(username='H1VAL', password=PASSWORD))

    def test_password_not_echoed_in_response(self):
        resp = self._post('wrong', NEW_PASSWORD, NEW_PASSWORD)
        body = resp.content.decode('utf-8')
        self.assertNotIn(NEW_PASSWORD, body, '响应回显了新密码')
        self.assertNotIn(PASSWORD, body, '响应回显了当前密码')


class CsrfTests(TestCase):
    def setUp(self):
        self.account = make_account('H1CSRF', RoleCode.SYSTEM_ADMIN)

    def test_post_without_csrf_rejected(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.account)

        resp = strict.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        self.assertEqual(resp.status_code, 403)
        # 未改密
        self.assertTrue(authenticate(username='H1CSRF', password=PASSWORD))


class MultiSessionTests(TestCase):
    """改密后：当前会话保持登录，其他会话应失效。"""

    def setUp(self):
        self.account = make_account('H1MULTI', RoleCode.SYSTEM_ADMIN)

        # 会话 A（旧会话）
        self.other = Client()
        self.other.force_login(self.account)
        self.assertEqual(self.other.get('/r4/units/').status_code, 200)

        # 会话 B（当前会话，执行改密）
        self.current = Client()
        self.current.force_login(self.account)

    def test_current_session_survives(self):
        self.current.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        self.assertEqual(self.current.get('/r4/units/').status_code, 200)

    def test_other_session_invalidated(self):
        self.current.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        resp = self.other.get('/r4/units/')
        self.assertIn(
            resp.status_code, (302, 403),
            '改密后旧会话仍可访问（status={}），存在会话劫持风险'.format(resp.status_code),
        )
