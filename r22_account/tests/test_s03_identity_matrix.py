"""S03 验收矩阵：统一身份权威。

主任务书 S03 的验收点，逐条固化为断言：

1. 身份解析有**唯一权威来源**（``r22_account.identity.resolve_identity``）；
2. 不存在 ``session['info']`` 单凭旧会话放行的路径（info-only 不得授予访问）；
3. 新旧身份同时存在但链接缺失/不匹配 → **冲突并拒绝**，绝不降级；
4. 账号绑定用 ``LegacyAccountLink``，不以登录名/主键巧合判定；可见性可校验；
5. 不修改正式 ``AUTH_USER_MODEL``，也不把正式认证配置改成必须依赖本模块。

本文件是"以 S03 名义"的独立证据，与 ``test_g2_identity`` / ``test_g4_dual_identity``
互补（后者覆盖实现细节，本文件覆盖验收条款）。
"""
from django.conf import settings
from django.test import Client, TestCase, override_settings

from r22_account.identity import (
    KIND_ACCOUNT,
    KIND_ANONYMOUS,
    KIND_CONFLICT,
    KIND_DUAL,
    KIND_LEGACY,
)
from r22_account.tests import helpers as h

DUAL = {'identity_mode': 'dual', 'route_policy_enabled': True}
OFF = {'identity_mode': 'off', 'route_policy_enabled': True}
ACCOUNT_ONLY = {'identity_mode': 'account', 'route_policy_enabled': True}


def kind_of(client):
    status, payload = h.identity_payload(client)
    assert status == 200, 'identity endpoint returned {}'.format(status)
    return payload['kind']


@override_settings(R22_FLAGS=DUAL)
class IdentityResolutionMatrixTests(TestCase):
    """五类解析结果的完整矩阵。"""

    def test_anonymous_when_nothing_present(self):
        self.assertEqual(kind_of(Client()), KIND_ANONYMOUS)

    def test_legacy_only(self):
        client = Client()
        h.set_legacy_session(client, 'student', 'S900001')
        self.assertEqual(kind_of(client), KIND_LEGACY)

    def test_account_only(self):
        account = h.make_account('T900002', 'teacher')
        client = Client()
        h.login_account(client, account.login_name)
        self.assertEqual(kind_of(client), KIND_ACCOUNT)

    def test_dual_when_link_matches(self):
        account = h.make_account('T900003', 'teacher')
        h.link_legacy(account, 'teacher', 'T900003')
        client = Client()
        h.login_account(client, account.login_name)
        h.set_legacy_session(client, 'teacher', 'T900003')
        self.assertEqual(kind_of(client), KIND_DUAL)

    def test_conflict_when_link_missing(self):
        account = h.make_account('T900004', 'teacher')
        client = Client()
        h.login_account(client, account.login_name)
        h.set_legacy_session(client, 'teacher', 'T900004')
        self.assertEqual(kind_of(client), KIND_CONFLICT)

    def test_conflict_when_link_points_elsewhere(self):
        account = h.make_account('T900005', 'teacher')
        h.link_legacy(account, 'teacher', 'T999999')
        client = Client()
        h.login_account(client, account.login_name)
        h.set_legacy_session(client, 'teacher', 'T900005')
        self.assertEqual(kind_of(client), KIND_CONFLICT)

    def test_conflict_when_link_table_differs(self):
        """link 存在但表不符（teacher 账号却链到 student 表）也算冲突。"""
        account = h.make_account('T900006', 'teacher')
        h.link_legacy(account, 'student', 'T900006')
        client = Client()
        h.login_account(client, account.login_name)
        h.set_legacy_session(client, 'teacher', 'T900006')
        self.assertEqual(kind_of(client), KIND_CONFLICT)


@override_settings(R22_FLAGS=DUAL)
class FailClosedTests(TestCase):
    """验收点 2/3：不许用旧会话放大权限。"""

    def test_legacy_session_alone_never_becomes_authenticated(self):
        client = Client()
        h.set_legacy_session(client, 'admin', '900')
        _status, payload = h.identity_payload(client)
        self.assertEqual(payload['kind'], KIND_LEGACY)
        # 端点不暴露 is_authenticated 字段，用"没有 Account"表达同一事实：
        # legacy 身份只被允许走 legacy 路由，不能进 account 路由。
        self.assertFalse(payload['has_account'],
                         'legacy 身份不得携带 Account（否则等于被认证）')
        self.assertIsNone(payload['account_login'])

    def test_inactive_account_with_legacy_is_conflict_not_legacy(self):
        """停用的 Account 不能因为还留着旧 session 就被降级放行。"""
        account = h.make_account('T900010', 'teacher', is_active=False)
        client = Client()
        # 直接写入 session 模拟"改停用前登录、之后被停用"
        session = client.session
        session['_auth_user_id'] = str(account.pk)
        session['_auth_user_backend'] = 'r21_account.backends.AccountBackend'
        session['_auth_user_hash'] = account.get_session_auth_hash()
        session['info'] = {'id': 'T900010', 'type': 'teacher', 'name': 'x'}
        session.save()

        _status, payload = h.identity_payload(client)
        self.assertEqual(payload['kind'], KIND_CONFLICT)
        self.assertEqual(payload.get('reason'), 'invalid_account_with_legacy')

    def test_forged_session_type_is_not_identity(self):
        """伪造 ``session['info']['type']`` 为未知角色不得被当成身份。"""
        client = Client()
        session = client.session
        session['info'] = {'id': 'X1', 'type': 'superuser', 'name': 'forged'}
        session.save()
        self.assertEqual(kind_of(client), KIND_ANONYMOUS)

    def test_forged_session_without_id_is_not_identity(self):
        client = Client()
        session = client.session
        session['info'] = {'type': 'admin'}
        session.save()
        self.assertEqual(kind_of(client), KIND_ANONYMOUS)


@override_settings(R22_FLAGS=DUAL)
class RoutePolicyEnforcementTests(TestCase):
    """验收点 3：冲突与跨域身份在受保护路由上被拒绝。"""

    def test_conflict_denied_on_account_route(self):
        account = h.make_account('T900020', 'teacher')
        client = Client()
        h.login_account(client, account.login_name)
        h.set_legacy_session(client, 'teacher', 'T900020')  # 无 link

        resp = client.get('/r21/home/')
        self.assertIn(resp.status_code, (302, 403))

    def test_legacy_cannot_enter_account_route(self):
        client = Client()
        h.set_legacy_session(client, 'teacher', 'T900021')
        resp = client.get('/r21/home/')
        self.assertIn(resp.status_code, (302, 403))

    def test_account_cannot_enter_legacy_admin_route(self):
        account = h.make_account('T900022', 'teacher')
        client = Client()
        h.login_account(client, account.login_name)
        resp = client.get('/admin/admin/list/')
        self.assertIn(resp.status_code, (302, 403))

    def test_anonymous_denied_on_protected_route(self):
        resp = Client().get('/r21/home/')
        self.assertIn(resp.status_code, (302, 403))

    def test_identity_endpoint_is_exempt(self):
        """身份自省端点必须匿名可访问，否则登录流程拿不到身份信息。"""
        resp = Client().get('/identity/')
        self.assertEqual(resp.status_code, 200)


@override_settings(R22_FLAGS=OFF)
class ModeOffTests(TestCase):
    """验收点 5：不启用时完全不解析，绝不影响正式行为。"""

    def test_mode_off_reports_anonymous(self):
        client = Client()
        h.set_legacy_session(client, 'admin', '900')
        self.assertEqual(kind_of(client), KIND_ANONYMOUS)

    def test_mode_off_does_not_block_routes(self):
        client = Client()
        h.set_legacy_session(client, 'admin', '900')
        # 未启用身份层时，路由策略不应介入（由旧中间件自行处理）
        resp = client.get('/identity/')
        self.assertEqual(resp.status_code, 200)


@override_settings(R22_FLAGS=ACCOUNT_ONLY)
class AccountOnlyModeTests(TestCase):
    """account 模式下旧身份被完全忽略。"""

    def test_legacy_ignored(self):
        client = Client()
        h.set_legacy_session(client, 'student', 'S900030')
        self.assertEqual(kind_of(client), KIND_ANONYMOUS)

    def test_account_still_recognized(self):
        account = h.make_account('T900031', 'teacher')
        client = Client()
        h.login_account(client, account.login_name)
        self.assertEqual(kind_of(client), KIND_ACCOUNT)


class FormalAuthConfigUntouchedTests(TestCase):
    """验收点 5：正式认证配置未被本模块改写。

    实测事实（2026-10-30 核验）：本项目**从未**把 ``AUTH_USER_MODEL`` 指向自定义
    用户模型；``smass.settings`` 及 r4–r22 各 settings 均未设置该键，因此生效值
    是 Django 默认的 ``auth.User``。app01 里也不存在 ``UserInfo`` 类。
    本测试固化这一事实，避免后续误以为"曾经有一个 app01 用户模型被保护"。
    """

    def test_auth_user_model_is_django_default(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'auth.User')

    def test_no_settings_overrides_auth_user_model(self):
        """除隔离实验配置外，任何 settings 都不得覆盖 AUTH_USER_MODEL。"""
        from pathlib import Path
        base = Path(__file__).resolve().parents[2]
        settings_dir = base / 'smass'
        offenders = []
        for path in sorted(settings_dir.glob('settings*.py')):
            name = path.name
            # 这两个是"路径 B"隔离实验/原型配置，明确允许
            if name in {'settings_proto_user.py', 'settings_r22_b.py'}:
                continue
            text = path.read_text(encoding='utf-8')
            if 'AUTH_USER_MODEL' in text and '=' in text:
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith('AUTH_USER_MODEL'):
                        offenders.append(f'{name}: {stripped}')
        self.assertEqual(offenders, [], '出现未预期的 AUTH_USER_MODEL 覆盖')

    def test_formal_settings_do_not_load_r22(self):
        """正式 settings 不得挂载 r22_account（身份层不进入生产认证）。"""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2]
        text = (base / 'smass' / 'settings.py').read_text(encoding='utf-8')
        self.assertNotIn('r22_account', text)
        self.assertNotIn('IdentityMiddleware', text)
