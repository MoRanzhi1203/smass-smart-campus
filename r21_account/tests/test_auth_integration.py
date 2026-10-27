"""G1 核心验证：自定义 Backend + Account 与 Django 认证机制的真实集成。

计划 G1 第 1 条明确要求"不要假设设置自定义 AUTHENTICATION_BACKENDS 后
request.user 天然成为非 AUTH_USER_MODEL 的 Account"。本文件用**真实 HTTP 请求**
（Django test Client 会走完整中间件链）来证明或推翻这一点。

被测事实：
1. ``authenticate()`` 返回 ``Account`` 实例；
2. ``login()`` 写入 ``_auth_user_id``，且 ``request.user`` 就是 ``Account``；
3. ``get_session_auth_hash`` 生效（改密后旧 Session 失效/刷新）；
4. ``PermissionsMixin.has_perm`` 可用（角色 → Group → Permission）；
5. ``logout()`` 清除会话。
"""
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY
from django.test import TestCase

from r21_account.models import Account, RoleCode
from r21_account.services import (
    account_has_perm,
    ensure_role_groups,
    grant_role,
    revoke_role,
)

PASSWORD = 'InitPass#2024'


def make_account(login_name='T900001', person_type='teacher', must_change=False):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name='测试{}'.format(login_name), person_type=person_type
    )
    if not must_change:
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
    return account


class BackendContractTests(TestCase):
    """认证后端本身的行为。"""

    def test_authenticate_returns_account(self):
        make_account('T900002')

        from django.contrib.auth import authenticate

        result = authenticate(username='T900002', password=PASSWORD)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Account)

    def test_authenticate_rejects_wrong_password(self):
        make_account('T900003')

        from django.contrib.auth import authenticate

        self.assertIsNone(authenticate(username='T900003', password='wrong'))

    def test_authenticate_rejects_inactive(self):
        account = make_account('T900004')
        account.is_active = False
        account.save(update_fields=['is_active'])

        from django.contrib.auth import authenticate

        self.assertIsNone(authenticate(username='T900004', password=PASSWORD))


class RequestUserIntegrationTests(TestCase):
    """真实请求链路：request.user 必须是 Account。"""

    def setUp(self):
        self.account = make_account('T910001')

    def test_login_sets_session_and_request_user(self):
        resp = self.client.post(
            '/r21/login/', {'login_name': 'T910001', 'password': PASSWORD}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/r21/home/')

        session = self.client.session
        self.assertEqual(session[SESSION_KEY], str(self.account.pk))
        self.assertIn('r21_account.backends.AccountBackend', session[BACKEND_SESSION_KEY])

    def test_request_user_is_account_instance(self):
        self.client.post('/r21/login/', {'login_name': 'T910001', 'password': PASSWORD})

        resp = self.client.get('/r21/ping/')
        self.assertEqual(resp.status_code, 200)

        payload = resp.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['login_name'], 'T910001')

        # 关键断言：中间件解析出来的 request.user 类型就是 Account
        request_user = resp.wsgi_request.user
        self.assertIsInstance(request_user, Account)
        self.assertEqual(request_user.pk, self.account.pk)

    def test_anonymous_ping_is_rejected(self):
        resp = self.client.get('/r21/ping/')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.json()['ok'])

    def test_logout_clears_session(self):
        self.client.post('/r21/login/', {'login_name': 'T910001', 'password': PASSWORD})
        self.assertEqual(self.client.get('/r21/ping/').status_code, 200)

        self.client.get('/r21/logout/')

        self.assertEqual(self.client.get('/r21/ping/').status_code, 403)

    def test_wrong_password_records_failure_and_stays_anonymous(self):
        resp = self.client.post(
            '/r21/login/', {'login_name': 'T910001', 'password': 'bad-password'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '账号或密码错误')
        self.assertEqual(self.client.get('/r21/ping/').status_code, 403)


class SessionAuthHashTests(TestCase):
    """改密后旧会话应失效（get_session_auth_hash 生效）。"""

    def setUp(self):
        self.account = make_account('T920001')

    def test_password_change_invalidates_old_session(self):
        from django.test import Client

        old_client = Client()
        old_client.post('/r21/login/', {'login_name': 'T920001', 'password': PASSWORD})
        self.assertEqual(old_client.get('/r21/ping/').status_code, 200)

        # 通过改密页把密码换掉（会 update_session_auth_hash，当前客户端仍有效）
        change = old_client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': 'NewPass#2024',
            'confirm_password': 'NewPass#2024',
        })
        self.assertEqual(change.status_code, 200)
        self.assertContains(change, '密码已更新')
        self.assertEqual(old_client.get('/r21/ping/').status_code, 200)

        # 另一个"旧会话"（模拟改密前的另一个浏览器）应被判定失效
        other = Client()
        other.cookies = old_client.cookies.__class__()
        # 直接用旧 hash 复现：登录另一个 client 后再改密，验证旧 client 失效
        stale = Client()
        stale.post('/r21/login/', {'login_name': 'T920001', 'password': 'NewPass#2024'})

        # 管理员再次重置密码
        self.account.refresh_from_db()
        self.account.set_password('ResetPass#2024')
        self.account.must_change_password = False
        self.account.save()

        # stale 的会话哈希已不匹配 => 应被登出
        self.assertEqual(stale.get('/r21/ping/').status_code, 403)


class PermissionIntegrationTests(TestCase):
    """角色 → Group → Permission 的真实权限判定。"""

    def setUp(self):
        ensure_role_groups()
        self.account = make_account('T930001')

    def test_permission_before_grant(self):
        fresh = Account.objects.get(pk=self.account.pk)
        self.assertFalse(account_has_perm(fresh, 'view_data'))

    def test_permission_after_grant(self):
        grant_role(self.account, RoleCode.TEACHER, granted_by='tester')

        fresh = Account.objects.get(pk=self.account.pk)
        self.assertTrue(account_has_perm(fresh, 'view_data'))
        # 教师不应有管理角色权限
        self.assertFalse(account_has_perm(fresh, 'manage_roles'))

    def test_dangerous_permission_granted_to_nobody(self):
        grant_role(self.account, RoleCode.SYSTEM_ADMIN, granted_by='tester')

        fresh = Account.objects.get(pk=self.account.pk)
        self.assertTrue(account_has_perm(fresh, 'manage_roles'))
        # 关键：即使是系统管理员也没有危险批量删除权限
        self.assertFalse(account_has_perm(fresh, 'dangerous_bulk_delete'))

    def test_revoke_role_removes_permission(self):
        grant_role(self.account, RoleCode.TEACHER, granted_by='tester')
        self.assertTrue(
            account_has_perm(Account.objects.get(pk=self.account.pk), 'view_data')
        )

        revoke_role(self.account, RoleCode.TEACHER, revoked_by='tester')

        fresh = Account.objects.get(pk=self.account.pk)
        self.assertFalse(account_has_perm(fresh, 'view_data'))
        self.assertFalse(AccountRole_active_exists(fresh, RoleCode.TEACHER))


def AccountRole_active_exists(account, role):
    return account.roles.filter(role=role, revoked_at__isnull=True).exists()
