"""S02 密码生命周期测试。

覆盖主任务书 S02 的验收点：
- 策略可配置且**默认全部关闭**；
- 管理员一次性临时口令流程（标记强制改密 + 到期 + 会话世代 + 审计）；
- 改密/重置后**旧会话立即失效**，当前会话不被误伤；
- 强制改密中间件拦截（页面 302 / AJAX 403）；
- 遗留哈希与停用账号在策略开启时的判定；
- 权限：非管理员不能发放临时口令；
- 审计载荷不含明文口令。
"""
import json
import re

from django.conf import settings
from django.test import TestCase, override_settings

from app01 import models
from app01.services import accounts
from app01.services import password_lifecycle as lifecycle
from app01.tests import helpers

ENABLED = {
    'ENABLED': True,
    'FORCE_RESET_LEGACY': False,
    'FORCE_RESET_INACTIVE': False,
    'MAX_AGE_DAYS': 0,
    'TEMP_PASSWORD_TTL_MINUTES': 60,
    'DETECT_LEGACY_ON_LOGIN': True,
}
DISABLED = dict(ENABLED, ENABLED=False)
FORCE_LEGACY = dict(ENABLED, FORCE_RESET_LEGACY=True)
FORCE_INACTIVE = dict(ENABLED, FORCE_RESET_INACTIVE=True)

TEMP_URL = '/admin/admin/temp-password/'
FORCED_URL = '/account/password/forced/'
ADMIN_LIST = '/admin/admin/list/'


class PolicyTests(TestCase):
    """策略默认关闭 + 合并语义。"""

    def test_defaults_are_all_off(self):
        cfg = settings.PASSWORD_LIFECYCLE
        self.assertFalse(cfg['ENABLED'])
        self.assertFalse(cfg['FORCE_RESET_LEGACY'])
        self.assertFalse(cfg['FORCE_RESET_INACTIVE'])
        self.assertEqual(cfg['MAX_AGE_DAYS'], 0)

    def test_partial_override_falls_back_to_defaults(self):
        with override_settings(PASSWORD_LIFECYCLE={'ENABLED': True}):
            cfg = lifecycle.policy()
        self.assertTrue(cfg['ENABLED'])
        self.assertFalse(cfg['FORCE_RESET_LEGACY'])
        self.assertEqual(cfg['TEMP_PASSWORD_TTL_MINUTES'],
                         lifecycle.POLICY_DEFAULTS['TEMP_PASSWORD_TTL_MINUTES'])

    def test_lifecycle_disabled_by_default(self):
        self.assertFalse(lifecycle.lifecycle_enabled())


class TableAvailabilityTests(TestCase):
    """状态表可用性探测：缺表必须降级而不是抛错。"""

    def test_table_exists_in_test_database(self):
        lifecycle.reset_table_probe()
        self.assertTrue(lifecycle.table_available())

    def test_missing_table_degrades_gracefully(self):
        """模拟缺表：所有入口都应安全返回，而不是 500。"""
        lifecycle.reset_table_probe()
        with mock_table_unavailable():
            student, _pwd = helpers.make_student()
            self.assertIsNone(lifecycle.get_state('student', student.pk))
            self.assertTrue(lifecycle.session_is_current('student', student.pk, {}))
            self.assertTrue(lifecycle.evaluate(student, 'student')['enabled'] is False)
            result = lifecycle.sweep('student', dry_run=True)
            self.assertFalse(result['available'])


class mock_table_unavailable:
    """把表探测强制为不可用（上下文管理器）。"""

    def __enter__(self):
        from unittest import mock
        self._patch = mock.patch.object(
            lifecycle, 'table_available', lambda force=False: False)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        lifecycle.reset_table_probe()
        return False


@override_settings(PASSWORD_LIFECYCLE=ENABLED)
class TempPasswordIssueTests(TestCase):
    """管理员一次性临时口令。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()
        cls.student, _ = helpers.make_student()
        cls.before_hash = cls.student.password

    def setUp(self):
        lifecycle.reset_table_probe()
        self.client = helpers.logged_in_client('admin', self.admin.pk, self.admin_password)

    def test_issue_marks_must_change_and_writes_official_hash(self):
        resp = self.client.post(TEMP_URL, {'account_type': 'student', 'account_id': self.student.pk})
        self.assertEqual(resp.status_code, 200, resp.content[:400])
        data = json.loads(resp.content.decode('utf-8'))
        self.assertTrue(data['status'])
        raw = data['password']
        self.assertTrue(raw)

        fresh = models.Student.objects.get(pk=self.student.pk)
        self.assertTrue(fresh.password.startswith('pbkdf2_'), '临时口令必须是官方哈希')
        self.assertNotEqual(fresh.password, self.before_hash)
        self.assertNotIn(raw, fresh.password, '不得明文入库')

        state = lifecycle.get_state('student', fresh.pk)
        self.assertIsNotNone(state)
        self.assertTrue(state.must_change_password)
        self.assertFalse(state.legacy_hash_pending)
        self.assertIsNotNone(state.temp_password_expires_at)
        self.assertEqual(state.last_reset_by, '')
        self.assertEqual(state.session_epoch, 1)

    def test_issue_response_is_not_cacheable(self):
        resp = self.client.post(TEMP_URL, {'account_type': 'student', 'account_id': self.student.pk})
        self.assertIn('no-store', resp.headers.get('Cache-Control', ''))

    def test_issue_bumps_session_epoch_and_invalidates_old_sessions(self):
        student, password = helpers.make_student()
        old_client = helpers.logged_in_client('student', student.pk, password)

        # 旧会话此刻可用
        self.assertEqual(old_client.get('/student/users/profile/').status_code, 200)

        lifecycle.issue_temporary_password(
            models.Student.objects.get(pk=student.pk), 'student')

        # 重置后旧会话必须失效
        resp = old_client.get('/student/users/profile/')
        self.assertIn(resp.status_code, (302, 401), '旧会话应失效')

    def test_unknown_account_type_rejected(self):
        resp = self.client.post(TEMP_URL, {'account_type': 'nobody', 'account_id': 'x'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_account_rejected(self):
        resp = self.client.post(TEMP_URL, {'account_type': 'student', 'account_id': 'NO-SUCH'})
        self.assertEqual(resp.status_code, 404)

    def test_requires_post(self):
        resp = self.client.get(TEMP_URL)
        self.assertEqual(resp.status_code, 405)

    def test_audit_does_not_contain_plaintext(self):
        with self.assertLogs('smass.audit', level='INFO') as ctx:
            resp = self.client.post(TEMP_URL, {'account_type': 'student',
                                               'account_id': self.student.pk})
        raw = json.loads(resp.content.decode('utf-8'))['password']
        joined = '\n'.join(ctx.output)
        self.assertIn('password_reset_temp', joined)
        self.assertNotIn(raw, joined, '审计日志中出现一次性明文口令')


class TempPasswordPermissionTests(TestCase):
    """非管理员不得发放临时口令。"""

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.student_password = helpers.make_student()
        cls.other, _ = helpers.make_student()

    def test_student_cannot_issue(self):
        """学生不得发放临时口令。

        该端点位于 ``/admin/`` 前缀下，``AuthMiddleware`` 会先按角色前缀拒绝，
        因此实际拒绝形式是 302 跳管理员登录页（或 403）；两者都表示未获授权。
        """
        before = models.Student.objects.get(pk=self.other.pk).password
        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.post(TEMP_URL, {'account_type': 'student', 'account_id': self.other.pk})
        self.assertIn(resp.status_code, (302, 403))

        after = models.Student.objects.get(pk=self.other.pk).password
        self.assertEqual(before, after, '被拒绝的请求不得改动目标账号密码')

    def test_anonymous_cannot_issue(self):
        from django.test import Client
        resp = Client().post(TEMP_URL, {'account_type': 'student', 'account_id': self.other.pk})
        self.assertIn(resp.status_code, (302, 403))


class SessionEpochTests(TestCase):
    """会话世代机制。"""

    @classmethod
    def setUpTestData(cls):
        cls.student, cls.password = helpers.make_student()

    def setUp(self):
        lifecycle.reset_table_probe()

    def test_epoch_zero_when_state_missing(self):
        self.assertEqual(lifecycle.current_epoch('student', self.student.pk), 0)

    def test_bump_increments(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        lifecycle.bump_epoch('student', self.student.pk)
        lifecycle.bump_epoch('student', self.student.pk)
        self.assertEqual(lifecycle.current_epoch('student', self.student.pk), 2)

    def test_session_is_current_requires_matching_epoch(self):
        state = lifecycle.get_or_create_state('student', self.student.pk)
        session = {lifecycle.SESSION_EPOCH_KEY: state.session_epoch}
        with override_settings(PASSWORD_LIFECYCLE=ENABLED):
            self.assertTrue(lifecycle.session_is_current('student', self.student.pk, session))
            lifecycle.bump_epoch('student', self.student.pk)
            self.assertFalse(lifecycle.session_is_current('student', self.student.pk, session))

    def test_session_without_epoch_is_rejected_when_enabled(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        with override_settings(PASSWORD_LIFECYCLE=ENABLED):
            self.assertFalse(lifecycle.session_is_current('student', self.student.pk, {}))

    def test_disabled_lifecycle_never_rejects(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        lifecycle.bump_epoch('student', self.student.pk)
        with override_settings(PASSWORD_LIFECYCLE=DISABLED):
            self.assertTrue(lifecycle.session_is_current('student', self.student.pk, {}))

    def test_deactivated_account_session_invalid(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        state = lifecycle.get_state('student', self.student.pk)
        session = {lifecycle.SESSION_EPOCH_KEY: state.session_epoch}
        lifecycle.deactivate(self.student, 'student', reason='test')
        with override_settings(PASSWORD_LIFECYCLE=ENABLED):
            self.assertFalse(lifecycle.session_is_current('student', self.student.pk, session))


class ForcedChangeFlowTests(TestCase):
    """完整流程：临时口令 -> 强制改密 -> 恢复正常访问。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin, cls.admin_password = helpers.make_admin()
        cls.student, cls.student_password = helpers.make_student()

    def setUp(self):
        lifecycle.reset_table_probe()

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_full_forced_change_journey(self):
        admin_client = helpers.logged_in_client('admin', self.admin.pk, self.admin_password)
        resp = admin_client.post(TEMP_URL, {'account_type': 'student',
                                            'account_id': self.student.pk})
        temp = json.loads(resp.content.decode('utf-8'))['password']

        # 1) 用临时口令登录
        from django.test import Client
        client = Client()
        login_resp = helpers.login(client, 'student', self.student.pk, temp)
        self.assertEqual(login_resp.status_code, 302)

        # 2) 访问业务页被拦截到强制改密页
        blocked = client.get('/student/users/profile/')
        self.assertEqual(blocked.status_code, 302)
        self.assertIn(FORCED_URL, blocked.headers.get('Location', ''))

        # 3) 改密页可访问
        page = client.get(FORCED_URL)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '修改密码')

        # 4) 提交改密
        new_password = 'Brand#New2026'
        done = client.post(FORCED_URL, {
            'current_password': temp,
            'new_password': new_password,
            'confirm_password': new_password,
        })
        self.assertEqual(done.status_code, 302, done.content[:400])

        # 5) 标记清除，业务页恢复
        state = lifecycle.get_state('student', self.student.pk)
        self.assertFalse(state.must_change_password)
        self.assertIsNotNone(state.password_changed_at)
        self.assertEqual(client.get('/student/users/profile/').status_code, 200)

        # 6) 新密码生效、旧临时口令失效
        fresh = models.Student.objects.get(pk=self.student.pk)
        self.assertTrue(accounts.verify_password(fresh, new_password))
        self.assertFalse(accounts.verify_password(fresh, temp))

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_ajax_request_gets_403_json(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        state = lifecycle.get_state('student', self.student.pk)
        state.must_change_password = True
        state.save(update_fields=['must_change_password', 'updated_at'])

        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.get('/student/users/profile/',
                          headers={'x-requested-with': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 403)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data['code'], 'must_change_password')

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_wrong_current_password_rejected(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.post(FORCED_URL, {
            'current_password': 'Wrong#2024',
            'new_password': 'Brand#New2026',
            'confirm_password': 'Brand#New2026',
        })
        self.assertEqual(resp.status_code, 200)  # 重新渲染表单
        self.assertContains(resp, '当前密码不正确')

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_mismatched_confirmation_rejected(self):
        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.post(FORCED_URL, {
            'current_password': self.student_password,
            'new_password': 'Brand#New2026',
            'confirm_password': 'Brand#Other2026',
        })
        self.assertContains(resp, '两次输入的新密码不一致')

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_weak_password_rejected_by_policy(self):
        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.post(FORCED_URL, {
            'current_password': self.student_password,
            'new_password': '123',
            'confirm_password': '123',
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertTrue('密码' in body)

    @override_settings(PASSWORD_LIFECYCLE=ENABLED)
    def test_same_as_current_rejected(self):
        client = helpers.logged_in_client('student', self.student.pk, self.student_password)
        resp = client.post(FORCED_URL, {
            'current_password': self.student_password,
            'new_password': self.student_password,
            'confirm_password': self.student_password,
        })
        self.assertContains(resp, '新密码不能与当前密码相同')

    def test_anonymous_redirected_to_login(self):
        from django.test import Client
        resp = Client().get(FORCED_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.headers.get('Location', ''))


class EvaluateTests(TestCase):
    """强制重置判定。"""

    @classmethod
    def setUpTestData(cls):
        cls.student, _ = helpers.make_student()

    def setUp(self):
        lifecycle.reset_table_probe()

    def test_default_policy_never_forces(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        with override_settings(PASSWORD_LIFECYCLE=DISABLED):
            result = lifecycle.evaluate(self.student, 'student')
        self.assertFalse(result['must_change'])

    def test_legacy_hash_forced_only_when_policy_on(self):
        state = lifecycle.get_or_create_state('student', self.student.pk)
        state.legacy_hash_pending = True
        state.save(update_fields=['legacy_hash_pending', 'updated_at'])

        with override_settings(PASSWORD_LIFECYCLE=DISABLED):
            self.assertFalse(lifecycle.evaluate(self.student, 'student')['must_change'])
        with override_settings(PASSWORD_LIFECYCLE=FORCE_LEGACY):
            result = lifecycle.evaluate(self.student, 'student')
        self.assertTrue(result['must_change'])
        self.assertEqual(result['reason'], 'legacy_hash')

    def test_inactive_flagged(self):
        lifecycle.get_or_create_state('student', self.student.pk)
        lifecycle.deactivate(self.student, 'student', reason='suspended')
        with override_settings(PASSWORD_LIFECYCLE=FORCE_INACTIVE):
            result = lifecycle.evaluate(self.student, 'student')
        self.assertFalse(result['active'])
        self.assertTrue(result['must_change'])
        self.assertEqual(result['reason'], 'inactive')

    def test_max_age_policy(self):
        from django.utils import timezone
        state = lifecycle.get_or_create_state('student', self.student.pk)
        state.password_changed_at = timezone.now() - timezone.timedelta(days=200)
        state.save(update_fields=['password_changed_at', 'updated_at'])
        with override_settings(PASSWORD_LIFECYCLE=dict(ENABLED, MAX_AGE_DAYS=180)):
            result = lifecycle.evaluate(self.student, 'student')
        self.assertTrue(result['must_change'])
        self.assertEqual(result['reason'], 'max_age')


class SweepTests(TestCase):
    """批量登记：只标记、不重置。"""

    def setUp(self):
        lifecycle.reset_table_probe()

    def test_sweep_dry_run_writes_nothing(self):
        with mock_legacy_hash():
            student, _ = helpers.make_student()
            before = models.AccountSecurityState.objects.count()
            result = lifecycle.sweep('student', dry_run=True)
            after = models.AccountSecurityState.objects.count()

        self.assertTrue(result['available'])
        self.assertGreaterEqual(result['scanned'], 1)
        self.assertGreaterEqual(result['legacy'], 1)
        self.assertEqual(before, after, 'dry_run 不得写状态')
        self.assertEqual(result['created_states'], 0)

    def test_sweep_apply_creates_states_but_does_not_touch_passwords(self):
        with mock_legacy_hash():
            student, _ = helpers.make_student()
            original_hash = models.Student.objects.get(pk=student.pk).password
            result = lifecycle.sweep('student', dry_run=False)
            fresh = models.Student.objects.get(pk=student.pk)

        self.assertGreaterEqual(result['created_states'], 1)
        self.assertEqual(fresh.password, original_hash, 'sweep 绝不能改密码')
        state = lifecycle.get_state('student', student.pk)
        self.assertTrue(state.legacy_hash_pending)


class mock_legacy_hash:
    """把任意密码视为历史 MD5（便于验证标记逻辑，不依赖真实旧数据）。"""

    def __enter__(self):
        from unittest import mock
        self._patch = mock.patch.object(
            lifecycle, 'is_legacy_hash_encoded', lambda encoded: bool(encoded))
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False
