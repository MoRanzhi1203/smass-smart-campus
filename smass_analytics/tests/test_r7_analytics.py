"""R7：指标注册、计算、看板、导出与聚合安全。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_analytics import services
from smass_analytics.models import (
    DataQualityIssue,
    MetricDefinition,
    MetricSnapshot,
    ReportDefinition,
    ReportRun,
)
from smass_organization import services as org_services
from smass_organization.models import OrganizationMembership, StudentRecord
from smass_workflow import services as workflow_services

PASSWORD = 'R7Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r7_test')
    return Account.objects.get(pk=account.pk)


def enable(metric):
    return services.validate_metric(metric)


class MetricRegistryTests(TestCase):
    def test_register_is_disabled_by_default(self):
        metric = services.register_metric(
            'org_units_total', '组织数', 'organization'
        )
        self.assertFalse(metric.is_enabled)

    def test_duplicate_code_rejected(self):
        services.register_metric('org_units_total', '组织数', 'organization')
        with self.assertRaises(services.AnalyticsError):
            services.register_metric('org_units_total', '另一个', 'organization')

    def test_unknown_data_source_rejected(self):
        with self.assertRaises(services.AnalyticsError):
            services.register_metric('x', 'X', 'nonexistent')

    def test_validate_requires_implementation(self):
        metric = services.register_metric('not_implemented', '无实现', 'organization')
        with self.assertRaises(services.AnalyticsError):
            services.validate_metric(metric)

    def test_validate_rejects_source_mismatch(self):
        metric = services.register_metric(
            'org_units_total', '组织数', 'student'   # 实现是 organization
        )
        with self.assertRaises(services.AnalyticsError):
            services.validate_metric(metric)

    def test_validate_enables_metric(self):
        metric = services.register_metric('org_units_total', '组织数', 'organization')
        services.validate_metric(metric)
        metric.refresh_from_db()
        self.assertTrue(metric.is_enabled)
        self.assertIsNotNone(metric.validated_at)

    def test_disabled_metric_cannot_compute(self):
        metric = services.register_metric('org_units_total', '组织数', 'organization')
        account = make_account('R7A1', RoleCode.SYSTEM_ADMIN)
        with self.assertRaises(services.MetricNotEnabled):
            services.compute_metric(metric, account)


class MetricComputeTests(TestCase):
    def setUp(self):
        self.sys = make_account('R7SYS', RoleCode.SYSTEM_ADMIN)
        self.college_a = org_services.create_unit(code='CA', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(code='CB', name='B院', unit_type='college')
        for index in range(6):
            StudentRecord.objects.create(
                student_no='A{:03d}'.format(index), name='A学生{}'.format(index),
                unit=self.college_a,
            )
        for index in range(3):
            StudentRecord.objects.create(
                student_no='B{:03d}'.format(index), name='B学生{}'.format(index),
                unit=self.college_b,
            )

        year = academic_services.create_year('Y1', date(2025, 9, 1), date(2026, 8, 31))
        term = academic_services.create_term(year, '1', date(2025, 9, 1), date(2026, 1, 15))
        course = academic_services.create_course('C1', '课程1')
        academic_services.create_section(term, course, 'A')
        academic_services.create_section(term, course, 'B')

    def _metric(self, code, source):
        metric = services.register_metric(code, code, source)
        return enable(metric)

    def test_org_units_total_matches_direct_count(self):
        metric = self._metric('org_units_total', 'organization')
        value, meta = services.compute_metric(metric, self.sys)

        from smass_organization.models import OrganizationUnit

        self.assertEqual(int(value), OrganizationUnit.objects.count())

    def test_students_scoped_matches_direct_count_for_admin(self):
        metric = self._metric('students_scoped', 'student')
        value, _meta = services.compute_metric(metric, self.sys)
        self.assertEqual(int(value), StudentRecord.objects.count())

    def test_sections_visible_matches_direct_count(self):
        metric = self._metric('sections_visible', 'academic')
        value, _meta = services.compute_metric(metric, self.sys)

        from smass_academic.models import TeachingSection

        self.assertEqual(int(value), TeachingSection.objects.count())

    def test_workflow_instances_count(self):
        metric = self._metric('workflow_instances', 'workflow')
        value, _meta = services.compute_metric(metric, self.sys)
        self.assertEqual(int(value), 0)

    def test_snapshot_written_with_hashes(self):
        metric = self._metric('org_units_total', 'organization')
        services.compute_metric(metric, self.sys)

        snapshot = MetricSnapshot.objects.filter(metric=metric).first()
        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.scope_hash)
        self.assertTrue(snapshot.query_hash)

    def test_same_scope_same_hash(self):
        metric = self._metric('org_units_total', 'organization')
        _v1, meta1 = services.compute_metric(metric, self.sys)
        _v2, meta2 = services.compute_metric(metric, self.sys)
        self.assertEqual(meta1['scope_hash'], meta2['scope_hash'])
        self.assertEqual(meta1['query_hash'], meta2['query_hash'])


class AggregationSecurityTests(TestCase):
    """R7-05：跨院聚合不泄漏 + 小样本抑制。"""

    def setUp(self):
        self.college_a = org_services.create_unit(code='CA', name='A院', unit_type='college')
        self.college_b = org_services.create_unit(code='CB', name='B院', unit_type='college')

        for index in range(8):
            StudentRecord.objects.create(
                student_no='A{:03d}'.format(index), name='A{}'.format(index),
                unit=self.college_a,
            )
        # B 院只有 2 人（低于默认阈值 5）
        for index in range(2):
            StudentRecord.objects.create(
                student_no='B{:03d}'.format(index), name='B{}'.format(index),
                unit=self.college_b,
            )

        self.admin_a = make_account('R7CA', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_a, unit=self.college_a)
        self.admin_b = make_account('R7CB', RoleCode.COLLEGE_ADMIN)
        OrganizationMembership.objects.create(account=self.admin_b, unit=self.college_b)

        self.metric = services.register_metric('students_scoped', '可见学生', 'student')
        enable(self.metric)

    def test_college_admin_a_sees_only_own(self):
        value, _meta = services.compute_metric(self.metric, self.admin_a)
        self.assertEqual(int(value), 8)

    def test_small_group_suppressed(self):
        """B 院只有 2 人 < 阈值 5 -> 抑制为 0 并记录质量问题。"""
        value, meta = services.compute_metric(self.metric, self.admin_b)
        self.assertEqual(int(value), 0)
        self.assertTrue(meta['suppressed'])
        self.assertTrue(
            DataQualityIssue.objects.filter(code='SMALL_SAMPLE').exists()
        )

    def test_no_cross_college_leak(self):
        value_a, _ = services.compute_metric(self.metric, self.admin_a)
        self.assertNotEqual(int(value_a), 10)   # 不是总数
        self.assertEqual(int(value_a), 8)       # 只是本院

    def test_account_without_role_computes_zero(self):
        nobody = make_account('R7NOB', None)
        value, _meta = services.compute_metric(self.metric, nobody)
        self.assertEqual(int(value), 0)


class ReportTests(TestCase):
    def setUp(self):
        self.sys = make_account('R7RSYS', RoleCode.SYSTEM_ADMIN)
        org_services.create_unit(code='C1', name='学院', unit_type='college')

        self.m1 = enable(services.register_metric(
            'org_units_total', '组织数', 'organization'))
        self.m2 = enable(services.register_metric(
            'students_scoped', '学生数', 'student'))

        self.report = services.create_report(
            'RPT1', '综合报表', metric_codes=['org_units_total', 'students_scoped'],
            permission_roles=['system_admin'],
        )

    def test_disabled_report_rejected(self):
        with self.assertRaises(services.AnalyticsError):
            services.run_report(self.report, self.sys)

    def test_report_runs_and_records_hash(self):
        self.report.is_enabled = True
        self.report.save(update_fields=['is_enabled'])

        rows, meta = services.run_report(self.report, self.sys)

        self.assertEqual(len(rows), 2)
        self.assertTrue(meta['query_hash'])
        self.assertTrue(ReportRun.objects.filter(report=self.report).exists())

    def test_unauthorized_role_rejected(self):
        self.report.is_enabled = True
        self.report.save(update_fields=['is_enabled'])
        teacher = make_account('R7T', RoleCode.TEACHER, 'teacher')

        with self.assertRaises(services.AccessError):
            services.run_report(self.report, teacher)

    def test_export_contains_hash_and_is_reproducible(self):
        self.report.is_enabled = True
        self.report.save(update_fields=['is_enabled'])

        text1, meta1 = services.export_report_csv(self.report, self.sys)
        text2, meta2 = services.export_report_csv(self.report, self.sys)

        self.assertIn('query_hash', text1)
        self.assertIn('org_units_total', text1)
        self.assertEqual(meta1['query_hash'], meta2['query_hash'])


class AnalyticsViewTests(TestCase):
    def setUp(self):
        self.sys = make_account('R7V', RoleCode.SYSTEM_ADMIN)
        self.teacher = make_account('R7VT', RoleCode.TEACHER, 'teacher')
        org_services.create_unit(code='C1', name='学院', unit_type='college')
        enable(services.register_metric('org_units_total', '组织数', 'organization'))

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/r7/dashboard/').status_code, 403)

    def test_dashboard_renders_values(self):
        self.client.force_login(self.sys)
        resp = self.client.get('/r7/dashboard/')

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('org_units_total', body)
        self.assertIsNotNone(resp.content)

    def test_metric_list_json(self):
        self.client.force_login(self.sys)
        resp = self.client.get('/r7/metrics/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(resp.status_code, 200)
        codes = {row['code'] for row in resp.json()['rows']}
        self.assertIn('org_units_total', codes)

    def test_health(self):
        resp = self.client.get('/r7/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
