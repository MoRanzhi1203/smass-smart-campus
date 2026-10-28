"""G4：五类双身份解析与路由策略（含降级/伪造/撤销等负面场景）。"""
from django.test import TestCase, override_settings

from r21_account import services
from r21_account.models import Account, RoleCode
from r22_account.tests import helpers

JSON = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class RoutePolicyTests(TestCase):
    def setUp(self):
        services.ensure_role_groups()

    def _legacy_ok(self):
        status = self.client.get('/legacy-parity/').status_code
        return status == 200

    def _account_route_ok(self):
        status = self.client.post('/r22/audit/probe/', **JSON).status_code
        return status == 200

    # ---- 1. 仅 legacy ----
    def test_legacy_only_can_use_legacy_route_not_account_route(self):
        helpers.set_legacy_session(self.client, 'teacher', 'T600001')

        self.assertTrue(self._legacy_ok())
        self.assertEqual(
            self.client.post('/r22/audit/probe/', **JSON).status_code, 403
        )

    # ---- 2. 仅 account ----
    def test_account_only_can_use_account_route_not_legacy_route(self):
        account = helpers.make_account('T600002')
        helpers.login_account(self.client, 'T600002')

        self.assertTrue(self._account_route_ok())
        self.assertEqual(
            self.client.get('/legacy-parity/', **JSON).status_code, 403
        )

    # ---- 3. dual（link 匹配）----
    def test_dual_identity_can_use_both_routes(self):
        account = helpers.make_account('T600003')
        helpers.link_legacy(account, 'teacher', 'T600003')
        helpers.login_account(self.client, 'T600003')
        helpers.set_legacy_session(self.client, 'teacher', 'T600003')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'dual')

        self.assertTrue(self._legacy_ok())
        self.assertTrue(self._account_route_ok())

    # ---- 4. conflict（有 link 但不匹配）----
    def test_conflict_denied_on_both_routes(self):
        account = helpers.make_account('T600004')
        helpers.link_legacy(account, 'teacher', 'T600004')
        helpers.login_account(self.client, 'T600004')
        # 旧 session 指向另一个人 → 冲突
        helpers.set_legacy_session(self.client, 'teacher', 'OTHER-ID')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'conflict')
        self.assertEqual(payload['reason'], 'link_mismatch')

        self.assertEqual(self.client.get('/legacy-parity/', **JSON).status_code, 403)
        self.assertEqual(self.client.post('/r22/audit/probe/', **JSON).status_code, 403)

    # ---- 5. anonymous ----
    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/legacy-parity/', **JSON).status_code, 403)
        self.assertEqual(self.client.post('/r22/audit/probe/', **JSON).status_code, 403)

    # ---- 6. 停用 account 不得降级为 legacy ----
    def test_disabled_account_does_not_fall_back_to_legacy(self):
        account = helpers.make_account('T600005')
        helpers.link_legacy(account, 'teacher', 'T600005')
        helpers.login_account(self.client, 'T600005')
        helpers.set_legacy_session(self.client, 'teacher', 'T600005')

        account.is_active = False
        account.save(update_fields=['is_active'])

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'conflict')
        self.assertEqual(payload['reason'], 'invalid_account_with_legacy')

        self.assertEqual(self.client.get('/legacy-parity/', **JSON).status_code, 403)

    # ---- 7. 伪造 legacy session 不提升 ----
    def test_forged_legacy_session_cannot_reach_account_route(self):
        helpers.set_legacy_session(self.client, 'admin', '001')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'legacy')
        self.assertEqual(
            self.client.post('/r22/audit/probe/', **JSON).status_code, 403
        )

    # ---- 8. 未加链接的 account + legacy → conflict ----
    def test_account_without_link_plus_legacy_is_conflict(self):
        helpers.make_account('T600006')
        helpers.login_account(self.client, 'T600006')
        helpers.set_legacy_session(self.client, 'teacher', 'T600006')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'conflict')
        self.assertEqual(payload['reason'], 'link_mismatch')

    # ---- 9. 特性开关关闭路由策略 ----
    @override_settings(R22_FLAGS={
        'identity_mode': 'dual', 'route_policy_enabled': False,
        'audit_enabled': True, 'dry_run': False,
    })
    def test_route_policy_disabled_lets_request_through(self):
        # 匿名也能到达视图（策略关闭），但视图本身不要求登录
        self.assertEqual(self.client.get('/legacy-parity/').status_code, 200)


class RoleRevocationTests(TestCase):
    def setUp(self):
        services.ensure_role_groups()

    def test_role_revocation_removes_permission_immediately(self):
        account = helpers.make_account('T600007')
        services.grant_role(account, RoleCode.SYSTEM_ADMIN, granted_by='test')
        fresh = Account.objects.get(pk=account.pk)
        self.assertTrue(services.account_has_perm(fresh, 'manage_roles'))

        services.revoke_role(account, RoleCode.SYSTEM_ADMIN, revoked_by='test')
        fresh = Account.objects.get(pk=account.pk)
        self.assertFalse(services.account_has_perm(fresh, 'manage_roles'))

    def test_identity_does_not_grant_permissions(self):
        """身份类型本身不授予任何权限：account 身份 + 无角色 → 无 view_data。"""
        account = helpers.make_account('T600008')
        helpers.link_legacy(account, 'student')
        helpers.login_account(self.client, 'T600008')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'account')

        fresh = Account.objects.get(pk=account.pk)
        self.assertFalse(services.account_has_perm(fresh, 'view_data'))


class ModeACcountOnlyTests(TestCase):
    @override_settings(R22_FLAGS={
        'identity_mode': 'account', 'route_policy_enabled': True,
        'audit_enabled': True, 'dry_run': False,
    })
    def test_legacy_session_ignored_in_account_mode(self):
        helpers.set_legacy_session(self.client, 'teacher', 'T600009')

        status, payload = helpers.identity_payload(self.client)
        self.assertEqual(payload['kind'], 'anonymous')
        self.assertEqual(payload['reason'], 'account_mode_no_account')
