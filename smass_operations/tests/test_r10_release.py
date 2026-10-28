"""R10：导航、安装预检、全链路 E2E。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_analytics import services as analytics_services
from smass_api import services as api_services
from smass_organization import services as org_services
from smass_organization.models import StudentRecord
from smass_workflow import services as workflow_services

PASSWORD = 'R10Pass#2024'


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='r10_test')
    return Account.objects.get(pk=account.pk)


class NavigationTests(TestCase):
    def test_nav_page_renders_for_anonymous(self):
        resp = self.client.get('/r10/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('r10-nav', body)
        self.assertIn('未登录', body)

    def test_nav_page_shows_roles_when_logged_in(self):
        account = make_account('R10NAV', RoleCode.SYSTEM_ADMIN)
        self.client.force_login(account)

        resp = self.client.get('/r10/')
        body = resp.content.decode('utf-8')
        self.assertIn('R10NAV', body)
        self.assertIn('system_admin', body)

    def test_nav_links_point_to_real_modules(self):
        resp = self.client.get('/r10/')
        body = resp.content.decode('utf-8')
        for href in ('/r4/units/', '/r5/years/', '/r6/definitions/',
                     '/r7/dashboard/', '/api/v1/openapi.json', '/r9/health/'):
            self.assertIn(href, body, '导航缺少 {}'.format(href))

    def test_nav_targets_are_reachable(self):
        """导航指向的端点都应存在（health 公开，其余鉴权后可用）。"""
        for path in ('/r9/health/', '/api/v1/openapi.json'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

    def test_responsive_meta_present(self):
        resp = self.client.get('/r10/')
        self.assertIn('viewport', resp.content.decode('utf-8'))


class InstallPreflightTests(TestCase):
    def test_migrations_are_consistent(self):
        """安装预检核心：没有未应用的迁移。"""
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.assertEqual(plan, [], '存在未应用迁移: {}'.format(plan[:3]))

    def test_readiness_reports_ok(self):
        resp = self.client.get('/r9/ready/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_health_is_alive(self):
        resp = self.client.get('/r9/health/')
        self.assertEqual(resp.json()['status'], 'alive')


class FullChainE2ETests(TestCase):
    """R10-05：R4 → R5 → R6 → R7 → R8 全链路一次跑通。"""

    def setUp(self):
        core_services.ensure_role_groups()
        self.account = make_account('R10E2E', RoleCode.SYSTEM_ADMIN)

    def test_full_chain(self):
        # ---- R4：组织 + 学生 ----
        college = org_services.create_unit(code='R10C', name='R10学院', unit_type='college')
        major = org_services.create_unit(code='R10M', name='R10专业',
                                         unit_type='major', parent=college)
        klass = org_services.create_unit(code='R10K', name='R10班级',
                                         unit_type='class', parent=major)
        student_record = StudentRecord.objects.create(
            student_no='R10S001', name='R10学生', unit=klass
        )
        self.assertEqual(org_services.scoped_students(self.account).count(), 1)

        # ---- R5：学年/学期/课程/教学班/任课/修读 ----
        year = academic_services.create_year('R10-Y', date(2025, 9, 1), date(2026, 8, 31))
        term = academic_services.create_term(year, '1', date(2025, 9, 1), date(2026, 1, 15))
        course = academic_services.create_course('R10-CS', 'R10课程', credit=3)
        section = academic_services.create_section(term, course, 'A', capacity=30)

        teacher = make_account('R10T', RoleCode.TEACHER, 'teacher')
        academic_services.assign_teacher(section, teacher, assigned_by='e2e')
        self.assertTrue(academic_services.can_teach(teacher, section))

        student_account = make_account('R10S', RoleCode.STUDENT, 'student')
        academic_services.enroll(section, student_account)
        self.assertEqual(academic_services.student_sections(student_account).count(), 1)

        # ---- R6：流程定义 → 实例 → 审批 ----
        definition = workflow_services.create_definition('R10-FLOW', 'R10审批')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '发起', 'start', order=0)
        workflow_services.add_node(version, 'approve', '审批', 'approval', order=1)
        workflow_services.add_node(version, 'end', '完成', 'end', order=2)
        workflow_services.add_transition(version, 'start', 'approve', 'submit')
        workflow_services.add_transition(version, 'approve', 'end', 'approve')
        workflow_services.publish_version(version)

        instance = workflow_services.start_instance(
            version, subject_type='student_record',
            subject_id=student_record.student_no, created_by='R10E2E',
        )
        workflow_services.transition(instance, 'submit', actor='R10E2E')
        instance = workflow_services.transition(instance, 'approve', actor='R10E2E')
        self.assertEqual(instance.status, 'approved')

        # ---- R7：指标（与直接聚合对账）----
        metric = analytics_services.register_metric(
            'org_units_total', '组织数', 'organization'
        )
        analytics_services.validate_metric(metric)
        value, meta = analytics_services.compute_metric(metric, self.account)

        from smass_organization.models import OrganizationUnit

        self.assertEqual(int(value), OrganizationUnit.objects.count())
        self.assertTrue(meta['query_hash'])

        # ---- R8：API ----
        account, raw = api_services.create_service_account(
            'r10-e2e', scopes=[api_services.SCOPE_READ_UNITS]
        )
        resp = self.client.get(
            '/api/v1/units/', HTTP_AUTHORIZATION='Bearer {}'.format(raw)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()['total'], 3)

        # ---- 跨模块不变量 ----
        self.assertEqual(student_record.unit.code, 'R10K')
        self.assertEqual(instance.version_id, version.pk)
        self.assertTrue(
            analytics_services.latest_snapshot(metric) is not None
        )

    def test_chain_respects_scope_across_modules(self):
        """跨模块一致性：组织 scope 在档案、指标、API 三处一致。"""
        college_a = org_services.create_unit(code='SA', name='A院', unit_type='college')
        college_b = org_services.create_unit(code='SB', name='B院', unit_type='college')
        # A 院 6 人（超过小样本抑制阈值 5），B 院 2 人
        for index in range(6):
            StudentRecord.objects.create(
                student_no='SA{:02d}'.format(index), name='A生{}'.format(index),
                unit=college_a,
            )
        for index in range(2):
            StudentRecord.objects.create(
                student_no='SB{:02d}'.format(index), name='B生{}'.format(index),
                unit=college_b,
            )

        admin_a = make_account('R10CA', RoleCode.COLLEGE_ADMIN)
        from smass_organization.models import OrganizationMembership

        OrganizationMembership.objects.create(account=admin_a, unit=college_a)

        # 1) 服务层
        self.assertEqual(org_services.scoped_students(admin_a).count(), 6)

        # 2) 指标层
        metric = analytics_services.register_metric(
            'students_scoped', '学生数', 'student'
        )
        analytics_services.validate_metric(metric)
        value, _meta = analytics_services.compute_metric(metric, admin_a)
        self.assertEqual(int(value), 6)   # > 阈值 5，不抑制

        # 3) API 层（服务账号默认空集，人员账号不受影响）
        account, raw = api_services.create_service_account(
            'r10-scope', scopes=[api_services.SCOPE_READ_STUDENTS]
        )
        resp = self.client.get(
            '/api/v1/students/', HTTP_AUTHORIZATION='Bearer {}'.format(raw)
        )
        self.assertEqual(resp.json()['total'], 0)
