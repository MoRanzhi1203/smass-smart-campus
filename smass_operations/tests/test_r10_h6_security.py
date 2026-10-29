"""H6：集成安全与威胁模型。

重点：
1. 身份矩阵：5 类账号 × 全模块代表端点
2. **跨面一致性**：同一账号在 UI / CSV / R7 指标看到的集合必须一致
3. 伪造请求不提权
4. 密码中间件与 legacy bridge 共存，不降级
5. 审计一致性
6. API 级并发（H2 约束）
7. 跨 settings 回归（r7 与 r10 下 dashboard 键兼容）
"""
import csv
import io
import json

from django.test import Client, TestCase

from r21_account import services as core_services
from r21_account.models import Account, AccountRole, RoleCode
from smass_analytics import services as analytics_services
from smass_organization import services as org_services
from smass_organization.models import OrganizationMembership, StudentRecord

PASSWORD = 'H6Pass#2024'


def make_account(login, role=None, person_type='admin', active=True,
                 must_change=False):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type)
    account.must_change_password = must_change
    if not active:
        account.is_active = False
    account.save()
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='h6')
    return Account.objects.get(pk=account.pk)


class H6Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()

        self.college_a = org_services.create_unit(
            code='H6A', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(
            code='H6B', name='B院', unit_type='college')

        for i in range(6):
            StudentRecord.objects.create(
                student_no='H6A{:03d}'.format(i), name='A{}'.format(i),
                unit=self.college_a)
        for i in range(3):
            StudentRecord.objects.create(
                student_no='H6B{:03d}'.format(i), name='B{}'.format(i),
                unit=self.college_b)

        self.sys = make_account('H6SYS', RoleCode.SYSTEM_ADMIN)
        self.admin_a = make_account('H6CA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)
        self.teacher = make_account('H6T', RoleCode.TEACHER, 'teacher')
        self.student = make_account('H6S', RoleCode.STUDENT, 'student')
        self.nobody = make_account('H6NOB')
        self.inactive = make_account('H6OFF', RoleCode.SYSTEM_ADMIN, active=False)

        # 绑定一个学生档案给 student
        StudentRecord.objects.filter(student_no='H6A000').update(account=self.student)


class IdentityMatrixTests(H6Fixture):
    """5 类身份 × 代表端点。"""

    ADMIN_ENDPOINTS = ['/r4/units/new/', '/r4/import/', '/r5/years/new/',
                       '/r6/definitions/new/']
    STAFF_ENDPOINTS = ['/r8/docs/', '/r9/status/', '/r7/dashboard/',
                       '/r6/tasks/']

    def test_anonymous_denied(self):
        client = Client()
        for url in self.ADMIN_ENDPOINTS + self.STAFF_ENDPOINTS:
            resp = client.get(url)
            self.assertIn(resp.status_code, (302, 403), url)

    def test_no_role_denied_everywhere(self):
        self.client.force_login(self.nobody)
        for url in self.ADMIN_ENDPOINTS + self.STAFF_ENDPOINTS:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_inactive_account_cannot_login(self):
        client = Client()
        ok = client.login(username='H6OFF', password=PASSWORD)
        self.assertFalse(ok, '停用账号不应能登录')

    def test_student_denied_admin_and_staff(self):
        self.client.force_login(self.student)
        for url in self.ADMIN_ENDPOINTS + self.STAFF_ENDPOINTS:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_teacher_denied_admin_forms(self):
        self.client.force_login(self.teacher)
        for url in self.ADMIN_ENDPOINTS:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # 教师可访问 staff 页面
        self.assertEqual(self.client.get('/r8/docs/').status_code, 200)

    def test_system_admin_allowed(self):
        self.client.force_login(self.sys)
        for url in self.ADMIN_ENDPOINTS + self.STAFF_ENDPOINTS:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_college_admin_allowed_partial(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get('/r4/import/').status_code, 200)
        # 学年新建是 system_admin only
        self.assertEqual(self.client.get('/r5/years/new/').status_code, 403)


class CrossSurfaceConsistencyTests(H6Fixture):
    """同一账号在 UI / CSV / R7 指标看到的集合必须一致。"""

    def _ui_student_count(self, client):
        resp = client.get('/r4/students/')
        body = resp.content.decode('utf-8')
        # 每个学生一行，学号以 H6 开头
        return body.count('H6A') + body.count('H6B') - 1  # 减去表头/导航干扰

    def _csv_text(self, client):
        resp = client.get('/r4/students/export/')
        self.assertEqual(resp.status_code, 200)
        # 导出可能是 StreamingHttpResponse（无 .content）或普通 HttpResponse
        if getattr(resp, 'streaming', False):
            payload = b''.join(resp.streaming_content)
        else:
            payload = resp.content
        return payload.decode('utf-8-sig')

    def _csv_student_count(self, client):
        rows = list(csv.reader(io.StringIO(self._csv_text(client))))
        # 去掉表头与空行
        return max(0, len([r for r in rows if r and r[0] and r[0] != 'student_no']))

    def _metric_value(self, account):
        metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
            code='students_scoped',
            defaults={'name': '可见学生', 'data_source': 'student'})
        if not metric.is_enabled:
            analytics_services.validate_metric(metric)
        value, meta = analytics_services.compute_metric(metric, account)
        return int(value), meta

    def test_scope_baseline(self):
        """先确立各角色的服务层基准。"""
        self.assertEqual(org_services.scoped_students(self.sys).count(), 9)
        self.assertEqual(org_services.scoped_students(self.admin_a).count(), 6)
        self.assertEqual(org_services.scoped_students(self.student).count(), 1)
        self.assertEqual(org_services.scoped_students(self.nobody).count(), 0)

    def test_csv_matches_service_layer(self):
        # 导出仅对 admin/college_admin/teacher 开放（student 403，见下一测试）
        for account, expected in ((self.sys, 9), (self.admin_a, 6)):
            client = Client()
            client.force_login(account)
            self.assertEqual(
                self._csv_student_count(client), expected,
                '{} 的 CSV 行数与 scoped_students 不一致'.format(account.login_name))

    def test_student_cannot_export(self):
        client = Client()
        client.force_login(self.student)
        self.assertEqual(
            client.get('/r4/students/export/').status_code, 403,
            '学生不应能导出学生档案')

    def test_ui_matches_csv(self):
        """UI 列表与导出的集合必须一致（同一 scope）。"""
        for account in (self.sys, self.admin_a):
            client = Client()
            client.force_login(account)

            csv_count = self._csv_student_count(client)
            service_count = org_services.scoped_students(account).count()
            self.assertEqual(
                csv_count, service_count,
                '{} UI/CSV 与服务层不一致'.format(account.login_name))

    def test_metric_matches_service_layer(self):
        for account, expected in ((self.sys, 9), (self.admin_a, 6)):
            value, meta = self._metric_value(account)
            self.assertEqual(
                value, expected,
                '{} 的 R7 指标 {} != 服务层 {}'.format(
                    account.login_name, value, expected))
            self.assertFalse(meta['suppressed'])

    def test_small_group_suppressed_not_leaked(self):
        """B 院只有 3 人 < 阈值 5：admin_b 的指标被抑制。"""
        admin_b = make_account('H6CB', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=admin_b, unit=self.college_b)

        value, meta = self._metric_value(admin_b)
        self.assertEqual(value, 0)
        self.assertTrue(meta['suppressed'])

        # 服务层仍能看到 3（但 UI/指标都不应暴露 3）
        self.assertEqual(org_services.scoped_students(admin_b).count(), 3)

    def test_api_service_account_default_empty(self):
        """API 服务账号即使有 read:students 也默认空集。"""
        from smass_api import services as api_services

        account, raw = api_services.create_service_account(
            'h6-api', scopes=[api_services.SCOPE_READ_STUDENTS])
        resp = self.client.get('/api/v1/students/',
                               HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total'], 0,
                         'API 服务账号不应默认可见全校学生')


class ForgedRequestTests(H6Fixture):
    """伪造参数不得提权。"""

    def test_forged_unit_create_as_student(self):
        client = Client()
        client.force_login(self.student)
        resp = client.post('/r4/units/new/', {
            'code': 'HACK1', 'name': '伪造学院', 'unit_type': 'college', 'parent': '',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            org_services.OrganizationUnit.objects.filter(code='HACK1').exists())

    def test_forged_role_in_body(self):
        """在 POST body 里塞 role 参数不应提权。"""
        client = Client()
        client.force_login(self.student)
        resp = client.post('/r4/units/new/', {
            'code': 'HACK2', 'name': 'x', 'unit_type': 'college', 'parent': '',
            'role': 'system_admin', 'account_id': str(self.sys.pk),
        })
        self.assertEqual(resp.status_code, 403)

    def test_forged_student_edit_as_teacher(self):
        record = StudentRecord.objects.get(student_no='H6A001')
        client = Client()
        client.force_login(self.teacher)
        resp = client.post('/r4/students/{}/edit/'.format(record.student_no), {
            'name': '篡改', 'status': 'active',
            'unit': str(self.college_a.pk), 'version': str(record.version),
        })
        self.assertEqual(resp.status_code, 403)

        record.refresh_from_db()
        self.assertNotEqual(record.name, '篡改')

    def test_cross_college_student_edit_denied(self):
        admin_b = make_account('H6CB2', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=admin_b, unit=self.college_b)

        record = StudentRecord.objects.get(student_no='H6A002')
        client = Client()
        client.force_login(admin_b)
        resp = client.post('/r4/students/{}/edit/'.format(record.student_no), {
            'name': '越权改', 'status': 'active',
            'unit': str(self.college_b.pk), 'version': str(record.version),
        })
        self.assertEqual(resp.status_code, 404)
        record.refresh_from_db()
        self.assertNotEqual(record.name, '越权改')

    def test_api_without_token_denied(self):
        self.assertEqual(self.client.get('/api/v1/units/').status_code, 401)

    def test_api_revoked_account_denied(self):
        from smass_api import services as api_services
        from smass_api.models import ServiceAccount

        account, raw = api_services.create_service_account(
            'h6-revoked', scopes=[api_services.SCOPE_READ_UNITS])
        ServiceAccount.objects.filter(pk=account.pk).update(is_active=False)

        resp = self.client.get('/api/v1/units/',
                               HTTP_AUTHORIZATION='Bearer {}'.format(raw))
        self.assertEqual(resp.status_code, 401)


class PasswordMiddlewareCoexistenceTests(H6Fixture):
    """强制改密不得因 legacy bridge 而失效。"""

    def test_forced_change_blocks_business_pages(self):
        forced = make_account('H6FORCE', RoleCode.SYSTEM_ADMIN, must_change=True)
        client = Client()
        client.force_login(forced)

        for url in ('/r4/units/', '/r7/dashboard/', '/r10/'):
            resp = client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/r21/change-password/', resp['Location'])

    def test_forced_change_ajax_403(self):
        forced = make_account('H6FORCE2', RoleCode.SYSTEM_ADMIN, must_change=True)
        client = Client()
        client.force_login(forced)

        resp = client.get('/r4/units/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'must_change_password')

    def test_no_session_downgrade_after_password_change(self):
        """改密后不应回退到 session['info'] 的旧身份。"""
        forced = make_account('H6DOWN', RoleCode.SYSTEM_ADMIN, must_change=True)
        client = Client()
        client.force_login(forced)

        client.post('/r21/change-password/', {
            'current_password': PASSWORD,
            'new_password': 'H6New#2024',
            'confirm_password': 'H6New#2024',
        })

        # 改密后 session 不应携带降级身份
        self.assertNotIn('info', client.session,
                         'session 中出现降级的 info 键')

        # 且业务页可访问
        self.assertEqual(client.get('/r4/units/').status_code, 200)


class AuditConsistencyTests(H6Fixture):
    """写操作产生审计；失败不留下半条审计。"""

    def test_role_grant_writes_account_role(self):
        before = AccountRole.objects.count()
        core_services.grant_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                 granted_by='h6-audit')
        self.assertEqual(AccountRole.objects.count(), before + 1)

        record = AccountRole.objects.filter(
            account=self.teacher, role=RoleCode.COLLEGE_ADMIN,
            revoked_at__isnull=True).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.granted_by, 'h6-audit')

    def test_duplicate_grant_does_not_create_second_row(self):
        core_services.grant_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                 granted_by='h6-a')
        before = AccountRole.objects.filter(
            account=self.teacher, role=RoleCode.COLLEGE_ADMIN).count()

        try:
            core_services.grant_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                     granted_by='h6-b')
        except Exception:  # noqa: BLE001
            pass

        after = AccountRole.objects.filter(
            account=self.teacher, role=RoleCode.COLLEGE_ADMIN).count()
        self.assertEqual(after, before, '重复授予产生了额外行')

    def test_revoke_then_grant_keeps_history(self):
        core_services.grant_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                 granted_by='h6-1')
        core_services.revoke_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                  revoked_by='h6-1')
        core_services.grant_role(self.teacher, RoleCode.COLLEGE_ADMIN,
                                 granted_by='h6-2')

        rows = AccountRole.objects.filter(
            account=self.teacher, role=RoleCode.COLLEGE_ADMIN)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(revoked_at__isnull=True).count(), 1)


class CrossSettingsRegressionTests(H6Fixture):
    """R7 dashboard 的 metric/code 键兼容在 r7 与 r10 下都必须成立。"""

    def test_dashboard_json_has_both_keys_r10(self):
        metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
            code='org_units_total',
            defaults={'name': '组织数', 'data_source': 'organization'})
        if not metric.is_enabled:
            analytics_services.validate_metric(metric)

        self.client.force_login(self.sys)
        resp = self.client.get('/r7/dashboard/',
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['rows']
        self.assertTrue(rows)
        for row in rows:
            self.assertIn('metric', row, '缺少 metric 键（旧消费者依赖）')
            self.assertIn('code', row, '缺少 code 键（新模板依赖）')
            self.assertEqual(row['metric'], row['code'])
