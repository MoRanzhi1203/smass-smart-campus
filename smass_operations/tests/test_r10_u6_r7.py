"""U6：R7 看板筛选、报表与授权导出（含抑制值不泄漏）。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_analytics import services
from smass_analytics.models import (
    DataQualityIssue,
    MetricDefinition,
    ReportDefinition,
    ReportRun,
)
from smass_organization import services as org_services
from smass_organization.models import OrganizationMembership, StudentRecord

PASSWORD = 'U6Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u6')
    return Account.objects.get(pk=account.pk)


class U6Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.sys = make_account('U6SYS', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('U6T', RoleCode.TEACHER, 'teacher')

        self.college_a = org_services.create_unit(code='U6A', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(code='U6B', name='B院', unit_type='college')

        # A 院 8 人（超阈值），B 院 2 人（低于阈值 -> 抑制）
        for i in range(8):
            StudentRecord.objects.create(
                student_no='U6A{:03d}'.format(i), name='A{}'.format(i), unit=self.college_a)
        for i in range(2):
            StudentRecord.objects.create(
                student_no='U6B{:03d}'.format(i), name='B{}'.format(i), unit=self.college_b)

        self.admin_a = make_account('U6CA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)
        self.admin_b = make_account('U6CB', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_b, unit=self.college_b)

        self.org_metric = services.register_metric(
            'org_units_total', '组织单元总数', 'organization',
            description='全部组织单元数量')
        services.validate_metric(self.org_metric)
        self.student_metric = services.register_metric(
            'students_scoped', '可见学生数', 'student',
            description='按数据范围过滤后的人数')
        services.validate_metric(self.student_metric)

        self.report = services.create_report(
            'U6RPT', 'U6 报表',
            metric_codes=['org_units_total', 'students_scoped'],
            permission_roles=['system_admin'],
        )
        self.report.is_enabled = True
        self.report.save(update_fields=['is_enabled'])

        self.client.force_login(self.sys)


class DashboardTests(U6Fixture):
    def test_dashboard_renders_kpi(self):
        resp = self.client.get('/r7/dashboard/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="kpi-grid"', body)
        self.assertIn('组织单元总数', body)
        self.assertIn('id="dashboard-table"', body)

    def test_dashboard_shows_real_values_for_admin(self):
        resp = self.client.get('/r7/dashboard/')
        body = resp.content.decode('utf-8')
        # 系统管理员：组织 2、学生 10
        self.assertIn('id="value-org_units_total">2.0<', body)
        self.assertIn('id="value-students_scoped">10.0<', body)

    def test_filter_by_source(self):
        resp = self.client.get('/r7/dashboard/?source=student')
        body = resp.content.decode('utf-8')
        self.assertIn('students_scoped', body)
        self.assertNotIn('org_units_total', body)

    def test_filter_unknown_source_shows_empty(self):
        resp = self.client.get('/r7/dashboard/?source=nonexistent')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="dashboard-empty"', resp.content.decode('utf-8'))


class SuppressionTests(U6Fixture):
    """关键：抑制时真实值不得出现在任何输出中。"""

    def setUp(self):
        super().setUp()
        # B 院管理员只有 2 人 < 阈值 5
        self.client.force_login(self.admin_b)

    def test_suppressed_badge_shown(self):
        resp = self.client.get('/r7/dashboard/')
        body = resp.content.decode('utf-8')
        self.assertIn('已抑制', body)

    def test_real_value_not_in_html(self):
        resp = self.client.get('/r7/dashboard/')
        body = resp.content.decode('utf-8')
        # 真实值 2 不应以数值形式出现
        self.assertNotIn('id="value-students_scoped"', body)
        # 有抑制标记
        self.assertIn('id="suppressed-students_scoped"', body)

    def test_suppression_notice_present(self):
        resp = self.client.get('/r7/dashboard/')
        self.assertIn('id="suppression-notice"', resp.content.decode('utf-8'))

    def test_blank_metric_json_value_is_zero(self):
        metric = self.student_metric
        value, meta = services.compute_metric(metric, self.admin_b)
        self.assertEqual(int(value), 0)
        self.assertTrue(meta['suppressed'])

    def test_quality_issue_recorded(self):
        services.compute_metric(self.student_metric, self.admin_b)
        self.assertTrue(
            DataQualityIssue.objects.filter(code='SMALL_SAMPLE').exists())

    def test_csv_does_not_leak_suppressed_value(self):
        admin_report = services.create_report(
            'U6SUP', '抑制报表', metric_codes=['students_scoped'])
        admin_report.is_enabled = True
        admin_report.save(update_fields=['is_enabled'])

        resp = self.client.get('/r7/reports/U6SUP/export/')
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode('utf-8')
        # CSV 中数值列应为 0（抑制后），不是 2
        self.assertIn('students_scoped', text)
        lines = [line for line in text.splitlines() if 'students_scoped' in line]
        self.assertTrue(lines)
        self.assertIn(',0', lines[0])


class ReportTests(U6Fixture):
    def test_report_list_shows_report(self):
        resp = self.client.get('/r7/metrics/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="report-table"', body)
        self.assertIn('U6RPT', body)
        self.assertIn('id="metric-table"', body)

    def test_report_detail_runs(self):
        resp = self.client.get('/r7/reports/U6RPT/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="report-table"', body)
        self.assertIn('id="meta-table"', body)
        self.assertIn('query_hash', body)

    def test_report_detail_records_run(self):
        before = ReportRun.objects.count()
        self.client.get('/r7/reports/U6RPT/')
        self.assertEqual(ReportRun.objects.count(), before + 1)

    def test_report_unknown_404(self):
        self.assertEqual(self.client.get('/r7/reports/NOPE/').status_code, 404)

    def test_report_disabled_shows_notice(self):
        disabled = services.create_report('U6OFF', '未启用报表')
        resp = self.client.get('/r7/reports/U6OFF/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="report-disabled"', resp.content.decode('utf-8'))

    def test_report_permission_denied(self):
        """报表只授权 system_admin，学院管理员应 403。"""
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get('/r7/reports/U6RPT/').status_code, 403)

    def test_export_returns_csv_with_hash(self):
        resp = self.client.get('/r7/reports/U6RPT/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('X-Query-Hash', resp.headers)
        self.assertIn('query_hash', resp.content.decode('utf-8'))

    def test_export_permission_denied(self):
        self.client.force_login(self.admin_a)
        self.assertEqual(
            self.client.get('/r7/reports/U6RPT/export/').status_code, 403)

    def test_teacher_cannot_export_admin_only_report(self):
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.get('/r7/reports/U6RPT/export/').status_code, 403)


class ScopeBeforeAggregateTests(U6Fixture):
    """scope 先于聚合：不同角色看到不同数值。"""

    def test_college_admin_sees_own_count_only(self):
        self.client.force_login(self.admin_a)
        resp = self.client.get('/r7/dashboard/')
        body = resp.content.decode('utf-8')
        # A 院 8 人（未抑制）
        self.assertIn('id="value-students_scoped">8.0<', body)

    def test_two_colleges_differ(self):
        _va, meta_a = services.compute_metric(self.student_metric, self.admin_a)
        _vb, meta_b = services.compute_metric(self.student_metric, self.admin_b)
        self.assertNotEqual(meta_a['scope_hash'], meta_b['scope_hash'])

    def test_series_endpoint_respects_permission(self):
        services.compute_metric(self.org_metric, self.sys)
        resp = self.client.get('/r7/metric-series/?code=org_units_total')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['ok'])
        self.assertGreaterEqual(len(payload['points']), 1)

    def test_series_unknown_metric_404(self):
        self.assertEqual(
            self.client.get('/r7/metric-series/?code=nope').status_code, 404)


class AnonymousTests(U6Fixture):
    def test_anonymous_denied(self):
        self.client.logout()
        for url in ('/r7/dashboard/', '/r7/metrics/', '/r7/reports/U6RPT/'):
            self.assertIn(self.client.get(url).status_code, (403, 302), url)
