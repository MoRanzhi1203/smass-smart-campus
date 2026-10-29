"""U7：R8 API 文档与 R9 运维页面的统一接入与权限矩阵。

重点：
- 两个页面都是 staff-only，匿名/学生 403；
- `/r8/docs/` 必须反映**真实** OpenAPI 端点（不是写死的示例）；
- 页面不得泄漏任何服务令牌；
- `/r9/status/` 明确标注 STAGING，且不提供任何写操作；
- API 侧 scope 强制、限流、幂等保持有效（回归）。
"""
import re

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_api import services as api_services
from smass_api.models import ServiceAccount

PASSWORD = 'U7Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u7')
    return Account.objects.get(pk=account.pk)


class U7Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        api_services.reset_rate_limits()
        self.admin = make_account('U7ADM', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('U7T', RoleCode.TEACHER, 'teacher')
        self.student = make_account('U7S', RoleCode.STUDENT, 'student')
        self.client.force_login(self.admin)


class ApiDocsPageTests(U7Fixture):
    def test_docs_requires_staff(self):
        for account, label in ((self.teacher, 'teacher'), ):
            self.client.force_login(account)
            self.assertEqual(
                self.client.get('/r8/docs/').status_code, 200,
                '{} 应可访问（staff）'.format(label))

    def test_docs_denied_for_student(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/r8/docs/').status_code, 403)

    def test_docs_denied_for_anonymous(self):
        self.client.logout()
        self.assertEqual(self.client.get('/r8/docs/').status_code, 403)

    def test_docs_lists_every_real_endpoint(self):
        """页面端点表必须与 openapi_schema() 完全一致。"""
        schema = api_services.openapi_schema()
        expected = set()
        for path, methods in schema['paths'].items():
            for method in methods:
                if method.startswith('x-'):
                    continue
                expected.add((method.upper(), '/api/v1' + path))

        resp = self.client.get('/r8/docs/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')

        missing = [pair for pair in expected if pair[1] not in body]
        self.assertEqual(missing, [], '文档页缺少端点: {}'.format(missing))

    def test_docs_shows_all_scopes(self):
        body = self.client.get('/r8/docs/').content.decode('utf-8')
        for scope in api_services.ALL_SCOPES:
            self.assertIn(scope, body, '缺少 scope: {}'.format(scope))

    def test_docs_does_not_leak_tokens(self):
        """创建服务账号后，页面中不得出现明文或摘要。"""
        account, raw = api_services.create_service_account(
            'u7-doc-probe', scopes=[api_services.SCOPE_READ_UNITS])

        body = self.client.get('/r8/docs/').content.decode('utf-8')
        self.assertNotIn(raw, body, '文档页泄漏了明文令牌')
        self.assertNotIn(account.token_hash, body, '文档页泄漏了令牌摘要')

    def test_docs_warns_about_default_empty_scope(self):
        body = self.client.get('/r8/docs/').content.decode('utf-8')
        self.assertIn('没有任何 scope', body)
        self.assertIn('不等于全校可见', body)

    def test_docs_marks_isolated_environment(self):
        body = self.client.get('/r8/docs/').content.decode('utf-8')
        self.assertIn('隔离演示环境', body)
        self.assertIn('合成数据', body)

    def test_openapi_json_is_public_but_readonly(self):
        resp = self.client.get('/api/v1/openapi.json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('openapi', resp.json())


class OpsStatusPageTests(U7Fixture):
    def test_status_requires_staff(self):
        resp = self.client.get('/r9/status/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="probe-table"', body)

    def test_status_denied_for_student(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/r9/status/').status_code, 403)

    def test_status_denied_for_anonymous(self):
        self.client.logout()
        self.assertEqual(self.client.get('/r9/status/').status_code, 403)

    def test_status_shows_staging_label(self):
        body = self.client.get('/r9/status/').content.decode('utf-8')
        self.assertIn('STAGING', body)
        self.assertIn('非生产环境', body)

    def test_status_shows_readiness_checks(self):
        body = self.client.get('/r9/status/').content.decode('utf-8')
        self.assertIn('database', body)
        self.assertIn('migrations', body)

    def test_status_shows_latency_percentiles(self):
        body = self.client.get('/r9/status/').content.decode('utf-8')
        for label in ('P50', 'P95', 'P99'):
            self.assertIn(label, body)

    def test_status_has_no_write_actions(self):
        """运维页只读：不应出现任何 POST 表单或修改全局配置的入口。"""
        body = self.client.get('/r9/status/').content.decode('utf-8')
        self.assertNotIn('method="post"', body.lower())
        self.assertNotIn('max_connections', body)
        self.assertNotIn('重启', body)

    def test_status_does_not_leak_secrets(self):
        body = self.client.get('/r9/status/').content.decode('utf-8')
        # 不应出现数据库口令、连接串等
        self.assertNotIn('password', body.lower())
        self.assertNotIn('mysql://', body.lower())


class ApiRegressionTests(U7Fixture):
    """API 侧不变量：scope 强制、限流、幂等（U7 不得破坏）。"""

    def test_scope_still_enforced(self):
        account, raw = api_services.create_service_account(
            'u7-reader', scopes=[api_services.SCOPE_READ_UNITS])

        ok = self.client.get('/api/v1/units/',
                             HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(ok.status_code, 200)

        denied = self.client.get('/api/v1/students/',
                                 HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(denied.status_code, 403)

    def test_default_scope_is_empty(self):
        account, raw = api_services.create_service_account('u7-bare')
        self.assertEqual(account.scopes, [])
        resp = self.client.get('/api/v1/units/',
                               HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(resp.status_code, 403)

    def test_read_students_does_not_mean_whole_school(self):
        account, raw = api_services.create_service_account(
            'u7-students', scopes=[api_services.SCOPE_READ_STUDENTS])
        resp = self.client.get('/api/v1/students/',
                               HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total'], 0)

    def test_rate_limit_still_enforced(self):
        account, raw = api_services.create_service_account(
            'u7-rl', scopes=[api_services.SCOPE_READ_UNITS], rate_limit=2)

        statuses = [
            self.client.get('/api/v1/units/',
                            HTTP_AUTHORIZATION='Bearer {}'.format(raw)).status_code
            for _ in range(4)
        ]
        self.assertIn(429, statuses)

    def test_idempotency_still_enforced(self):
        import json as _json

        account, raw = api_services.create_service_account(
            'u7-idem', scopes=[api_services.SCOPE_WRITE_STUDENTS])
        payload = _json.dumps({'records': [{'external_id': 'x1'}]})

        headers = {'HTTP_AUTHORIZATION': 'Bearer {}'.format(raw),
                   'HTTP_IDEMPOTENCY_KEY': 'u7-k1'}

        self.client.post('/api/v1/sync/', data=payload,
                         content_type='application/json', **headers)
        second = self.client.post('/api/v1/sync/', data=payload,
                                  content_type='application/json', **headers)

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get('Idempotent-Replayed'), 'true')

    def test_token_not_stored_in_plaintext(self):
        account, raw = api_services.create_service_account('u7-hash')
        self.assertNotEqual(account.token_hash, raw)
        self.assertEqual(len(account.token_hash), 64)
        # 数据库中不存在明文
        self.assertFalse(
            ServiceAccount.objects.filter(token_hash=raw).exists())


class CrossPageConsistencyTests(U7Fixture):
    """导航一致性：R8/R9 页面在侧边栏高亮，且从任意页可达。"""

    def test_nav_highlight_on_api_docs(self):
        body = self.client.get('/r8/docs/').content.decode('utf-8')
        active = re.findall(r'class="sm-nav-link is-active"[^>]*href="([^"]+)"', body)
        active += re.findall(r'href="([^"]+)"[^>]*class="sm-nav-link is-active"', body)
        self.assertIn('/r8/docs/', active)

    def test_nav_highlight_on_ops_status(self):
        body = self.client.get('/r9/status/').content.decode('utf-8')
        active = re.findall(r'class="sm-nav-link is-active"[^>]*href="([^"]+)"', body)
        active += re.findall(r'href="([^"]+)"[^>]*class="sm-nav-link is-active"', body)
        self.assertIn('/r9/status/', active)

    def test_all_staff_pages_reachable(self):
        staff_pages = [
            '/r8/docs/', '/r9/status/', '/r7/metrics/', '/r6/tasks/',
            '/r5/years/', '/r4/units/',
        ]
        for url in staff_pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)
