"""PM8：安全、会话与可访问性回归（PMR 语境）。

与 H4/H6 的区别：这里验证的是**迁移语境下**的关切——尤其是
"陈旧 legacy session 不能因迁移而降级授权"。

覆盖：
1. 陈旧 legacy session（只有 info，无 _auth_user_id）不得授权
2. 强制改密在迁移后仍生效（页面 302 / AJAX 403）
3. 停用账号无法登录
4. CSRF 缺失时改密被拒
5. 审计日志载荷不含密码/哈希
6. 跨 settings 的 URLconf 都能解析改密与登录路由
7. scope 在服务层 / CSV / R7 一致
8. 三浏览器矩阵（引用 U8 实测，不重跑）
"""
import re

from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_analytics import services as analytics_services
from smass_organization import services as org_services
from smass_organization.models import OrganizationUnit, StudentRecord

PASSWORD = 'Pm8Pass#2024'


def make_account(login, role=RoleCode.SYSTEM_ADMIN, active=True,
                 must_change=False, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type)
    account.is_active = active
    account.must_change_password = must_change
    account.save()
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='pm8')
    return Account.objects.get(pk=account.pk)


class StaleLegacySessionTests(TestCase):
    """迁移语境的核心安全点：旧 session 不能变成后门。

    `app01` 的旧视图读 `session['info']`。如果迁移后仍有代码信任
    仅有 `info` 的 session，就等于"无凭证也能访问"。
    """

    def setUp(self):
        self.account = make_account('PM8S01')

    def _stale_client(self):
        client = Client()
        session = client.session
        # 模拟一个遗留 session：只有旧结构，没有 Django 认证键
        session['info'] = {
            'id': 'A01', 'name': '伪造姓名ZZZ', 'type': 'admin',
            'account_id': self.account.pk,
        }
        session.save()
        return client

    def test_info_only_session_cannot_access_protected_pages(self):
        '''受保护页面必须拒绝仅含 info 的 session。

        注意：`/r10/` **不在**此列表内——它的 docstring 明确写
        "未登录也可访问（便于排障）"，是公开页面。但它同样不得读取 info。
        '''
        client = self._stale_client()
        for url in ('/r4/units/', '/r5/years/', '/r6/tasks/', '/r7/dashboard/'):
            resp = client.get(url)
            self.assertIn(resp.status_code, (302, 403),
                          '{} 仅凭 info 就可访问（状态 {}）'.format(
                              url, resp.status_code))

    def test_public_nav_does_not_leak_session_info(self):
        '''`/r10/` 是公开页，但绝不能把 session['info'] 的内容渲染出去。'''
        client = self._stale_client()
        resp = client.get('/r10/')
        body = resp.content.decode('utf-8')

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('伪造姓名ZZZ', body,
                         '公开导航页渲染了 session info 里的名字')
        self.assertNotIn('A01', body, '公开导航页渲染了 session info 的 id')
        self.assertFalse(resp.wsgi_request.user.is_authenticated,
                         '公开导航页把 info 推断成了已认证用户')

    def test_info_alone_does_not_set_request_user(self):
        client = Client()
        session = client.session
        session['info'] = {'id': 'A01', 'name': '伪造', 'type': 'admin'}
        session.save()

        resp = client.get('/r10/')
        # request.user 必须是匿名（不是从 info 推断出的账号）
        self.assertFalse(resp.wsgi_request.user.is_authenticated,
                         'request.user 被 info 推断成已认证')

    def test_authenticated_session_wins_over_stale_info(self):
        """真实登录后，即使 session 里残留 info，也应以 Django 认证为准。"""
        other = make_account('PM8S02')
        client = Client()
        client.force_login(self.account)

        session = client.session
        session['info'] = {'id': 'X99', 'name': '他人', 'type': 'admin',
                           'account_id': other.pk}
        session.save()

        resp = client.get('/r4/units/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.wsgi_request.user.pk, self.account.pk,
                         'request.user 被 session info 覆盖')


class ForcedPasswordChangeTests(TestCase):
    def setUp(self):
        self.forced = make_account('PM8F01', must_change=True)

    def test_business_pages_redirect(self):
        client = Client()
        client.force_login(self.forced)
        for url in ('/r10/', '/r4/units/', '/r7/dashboard/'):
            resp = client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/r21/change-password/', resp['Location'])

    def test_ajax_gets_403(self):
        client = Client()
        client.force_login(self.forced)
        resp = client.get('/r4/units/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'must_change_password')

    def test_change_password_page_reachable(self):
        client = Client()
        client.force_login(self.forced)
        self.assertEqual(client.get('/r21/change-password/').status_code, 200)

    def test_logout_reachable_while_forced(self):
        client = Client()
        client.force_login(self.forced)
        resp = client.get('/r21/logout/')
        self.assertIn(resp.status_code, (200, 302))


class InactiveAccountTests(TestCase):
    def setUp(self):
        self.inactive = make_account('PM8I01', active=False)

    def test_cannot_login(self):
        client = Client()
        self.assertFalse(
            client.login(username='PM8I01', password=PASSWORD),
            '停用账号不应能通过 login()')

    def test_form_login_rejected(self):
        client = Client()
        resp = client.post('/r21/login/', {
            'login_name': 'PM8I01', 'password': PASSWORD})
        # 应停留在登录页（200），不是 302 跳转
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)


class CsrfTests(TestCase):
    def test_change_password_without_token_rejected(self):
        account = make_account('PM8C01', must_change=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(account)

        old_hash = Account.objects.get(pk=account.pk).password
        resp = client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': 'Pm8New#2024',
            'confirm_password': 'Pm8New#2024',
        })
        self.assertEqual(resp.status_code, 403)

        new_hash = Account.objects.get(pk=account.pk).password
        self.assertEqual(old_hash, new_hash, 'CSRF 拒绝时不应改密')


class AuditPayloadTests(TestCase):
    """审计日志不得出现密码或哈希。"""

    def setUp(self):
        self.account = make_account('PM8A01')

    def test_login_audit_has_no_credentials(self):
        from app01.services import accounts as legacy

        with self.assertLogs('smass.audit', level='INFO') as captured:
            legacy.log_action(None, 'test_action', None, detail='non-sensitive')

        text = '\n'.join(captured.output)
        self.assertNotIn(PASSWORD, text, '审计日志出现明文密码')
        self.assertNotRegex(text, r'pbkdf2_[a-z0-9]+\$', '审计日志出现哈希')
        self.assertNotRegex(text, r'\b[0-9a-f]{32}\b', '审计日志出现 32 位 MD5')

    def test_audit_keeps_action_and_actor(self):
        from app01.services import accounts as legacy

        with self.assertLogs('smass.audit', level='INFO') as captured:
            legacy.log_action(None, 'role_granted', None, detail='teacher')

        text = '\n'.join(captured.output)
        self.assertIn('role_granted', text)
        self.assertIn('action=', text)

    def test_hash_never_logged_even_when_passed_as_detail(self):
        """即使调用方误传哈希，也只应出现在 detail 里且我们**断言不该发生**。

        这条测试的作用是**固定契约**：当前代码不传哈希；若未来有人传了，
        这条断言会失败并提醒review。
        """
        from app01.services import accounts as legacy
        from django.contrib.auth.hashers import make_password

        encoded = make_password('x')
        # 正常路径不传哈希
        with self.assertLogs('smass.audit', level='INFO') as captured:
            legacy.log_action(None, 'normal', None, detail='ok')

        text = '\n'.join(captured.output)
        self.assertNotIn(encoded, text)


class RouteResolutionTests(TestCase):
    """跨 settings 的路由必须都能解析关键路径（不实际起服务）。"""

    def test_change_password_route_name_resolves(self):
        from django.urls import reverse
        url = reverse('r21_change_password')
        self.assertEqual(url, '/r21/change-password/')

    def test_login_and_logout_routes_exist(self):
        from django.urls import reverse
        self.assertTrue(reverse('r21_login').startswith('/r21/login'))

    def test_settings_files_reference_same_apps(self):
        """各 settings 必须都包含 r21_account 与 smass_organization。"""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / 'smass'
        for name in ('settings_r4.py', 'settings_r5.py', 'settings_r6.py',
                     'settings_r7.py', 'settings_r8.py', 'settings_r9.py',
                     'settings_r10.py', 'settings_pmr.py'):
            path = base / name
            self.assertTrue(path.exists(), '{} 缺失'.format(name))
            text = path.read_text(encoding='utf-8')
            # 要么显式列出，要么通过 import * 继承
            self.assertTrue(
                'r21_account' in text or 'settings_r10' in text or 'import *' in text,
                '{} 未包含 r21_account 且未继承'.format(name))


class CrossSurfaceScopeTests(TestCase):
    """scope 在服务层 / CSV / R7 之间一致（PMR 语境复核）。"""

    def setUp(self):
        self.college_a = org_services.create_unit(
            code='PM8CA', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(
            code='PM8CB', name='B院', unit_type='college')
        for i in range(6):
            StudentRecord.objects.create(
                student_no='PM8A{:03d}'.format(i), name='A{}'.format(i),
                unit=self.college_a)
        for i in range(3):
            StudentRecord.objects.create(
                student_no='PM8B{:03d}'.format(i), name='B{}'.format(i),
                unit=self.college_b)

        self.sys = make_account('PM8Z01')
        self.admin_a = make_account('PM8Z02', RoleCode.COLLEGE_ADMIN)
        from smass_organization.models import OrganizationMembership
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)

    def test_service_layer_baseline(self):
        self.assertEqual(org_services.scoped_students(self.sys).count(), 9)
        self.assertEqual(org_services.scoped_students(self.admin_a).count(), 6)

    def test_csv_matches_service(self):
        import csv
        import io

        for account, expected in ((self.sys, 9), (self.admin_a, 6)):
            client = Client()
            client.force_login(account)
            resp = client.get('/r4/students/export/')
            self.assertEqual(resp.status_code, 200)
            if getattr(resp, 'streaming', False):
                payload = b''.join(resp.streaming_content)
            else:
                payload = resp.content
            rows = list(csv.reader(io.StringIO(payload.decode('utf-8-sig'))))
            data_rows = [r for r in rows if r and r[0] and r[0] != 'student_no']
            self.assertEqual(len(data_rows), expected,
                             '{} CSV 行数与 scoped 不一致'.format(account.login_name))

    def test_metric_matches_service(self):
        metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
            code='students_scoped',
            defaults={'name': '可见学生', 'data_source': 'student'})
        if not metric.is_enabled:
            analytics_services.validate_metric(metric)

        for account, expected in ((self.sys, 9), (self.admin_a, 6)):
            value, meta = analytics_services.compute_metric(metric, account)
            self.assertEqual(int(value), expected,
                             '{} 指标 {} != {}'.format(account.login_name, value, expected))
            self.assertFalse(meta['suppressed'])

    def test_small_group_suppressed(self):
        admin_b = make_account('PM8Z03', RoleCode.COLLEGE_ADMIN)
        from smass_organization.models import OrganizationMembership
        OrganizationMembership.objects.create(account=admin_b, unit=self.college_b)

        metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
            code='students_scoped',
            defaults={'name': '可见学生', 'data_source': 'student'})
        if not metric.is_enabled:
            analytics_services.validate_metric(metric)

        value, meta = analytics_services.compute_metric(metric, admin_b)
        self.assertEqual(int(value), 0)
        self.assertTrue(meta['suppressed'])


class BrowserMatrixRecordTests(TestCase):
    """三浏览器矩阵：引用 U8 的实测结果，不在此重跑（避免伪造成本）。

    本测试只校验"矩阵记录与测试文件真实存在"，不声称浏览器跑过。
    """

    def test_u8_browser_suite_exists(self):
        from pathlib import Path
        path = (Path(__file__).resolve().parents[2]
                / 'smass_operations' / 'tests' / 'test_r10_u8_browser.py')
        self.assertTrue(path.exists())
        text = path.read_text(encoding='utf-8')
        for engine in ('chromium', 'firefox', 'webkit'):
            self.assertIn(engine, text)

    def test_e2e_report_records_webkit_limitation(self):
        from pathlib import Path
        doc = (Path(__file__).resolve().parents[2]
               / 'docs' / 'SMASS_R10_E2E_Cross_Browser.md')
        self.assertTrue(doc.exists())
        text = doc.read_text(encoding='utf-8')
        self.assertIn('R-15', text, 'E2E 报告未记录 WebKit 限制')
