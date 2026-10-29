"""R10-01 补测：所有模块页面必须渲染统一导航（防退化）。

之前的 R10-01 测试只验证了 `/r10/` 页面本身，
没有验证 R4–R8 的**各模块页面**是否接入导航——这正是线上看到的缺口。
本文件逐个页面断言 ``#r10-nav`` 存在，并确认原有表格 id 未被破坏。
"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_analytics import services as analytics_services
from smass_organization import services as org_services
from smass_organization.models import StudentRecord
from smass_workflow import services as workflow_services

PASSWORD = 'R10Nav#2024'

#: (URL, 该页原有的表格/容器 id)
PAGES = [
    ('/r4/units/', 'unit-table'),
    ('/r4/students/', 'student-table'),
    ('/r5/years/', 'year-table'),
    ('/r5/terms/', 'term-table'),
    ('/r5/courses/', 'course-table'),
    ('/r5/sections/', 'section-table'),
    ('/r5/workspace/', 'workspace-table'),
    ('/r5/my-courses/', 'my-table'),
    ('/r6/definitions/', 'definition-table'),
    ('/r6/instances/', 'instance-table'),
    ('/r6/tasks/', 'task-table'),
    ('/r6/notifications/', 'notification-table'),
    ('/r7/dashboard/', 'dashboard-table'),
    ('/r7/metrics/', 'metric-table'),
]


class NavIntegrationTests(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = Account.objects.create_user(
            'R10NAVADM', PASSWORD, display_name='nav-admin', person_type='admin'
        )
        self.admin.must_change_password = False
        self.admin.save(update_fields=['must_change_password'])
        core_services.grant_role(self.admin, RoleCode.SYSTEM_ADMIN, granted_by='r10nav')
        self.admin = Account.objects.get(pk=self.admin.pk)

        # 少量数据，确保页面走"有数据"分支而不是 empty 分支
        college = org_services.create_unit(code='NV-C', name='导航学院', unit_type='college')
        StudentRecord.objects.create(student_no='NV-S1', name='导航学生', unit=college)

        year = academic_services.create_year('NV-Y', date(2025, 9, 1), date(2026, 8, 31))
        self.term = academic_services.create_term(
            year, '1', date(2025, 9, 1), date(2026, 1, 15))
        self.course = academic_services.create_course('NV-CS', '导航课程', credit=2)
        academic_services.create_section(self.term, self.course, 'A', capacity=10)

        definition = workflow_services.create_definition('NV-FLOW', '导航流程')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '开始', 'start')
        workflow_services.add_node(version, 'end', '结束', 'end')
        workflow_services.add_transition(version, 'start', 'end', 'submit')
        workflow_services.publish_version(version)
        workflow_services.start_instance(version, subject_type='demo', subject_id='1')

        metric = analytics_services.register_metric(
            'org_units_total', '组织数', 'organization')
        analytics_services.validate_metric(metric)
        analytics_services.register_metric(
            'students_scoped', '学生数', 'student')

        self.client.force_login(self.admin)

    def test_every_module_page_has_nav(self):
        missing = []
        for url, table_id in PAGES:
            resp = self.client.get(url)
            if resp.status_code != 200:
                self.fail('{} 返回 {}'.format(url, resp.status_code))
            body = resp.content.decode('utf-8')
            if 'id="sm-sidebar"' not in body:
                missing.append(url)

        self.assertEqual(missing, [], '以下页面缺少统一导航: {}'.format(missing))

    def test_every_module_page_keeps_its_table(self):
        for url, table_id in PAGES:
            resp = self.client.get(url)
            body = resp.content.decode('utf-8')
            self.assertIn(
                'id="{}"'.format(table_id), body,
                '{} 丢失了容器 {}'.format(url, table_id),
            )

    def test_nav_links_present_on_module_page(self):
        resp = self.client.get('/r4/units/')
        body = resp.content.decode('utf-8')
        for href in ('/r4/units/', '/r5/years/', '/r6/definitions/',
                     '/r7/dashboard/', '/r8/docs/', '/r9/status/'):
            self.assertIn(href, body)

    def test_nav_shows_current_user(self):
        resp = self.client.get('/r5/years/')
        body = resp.content.decode('utf-8')
        # 新外壳优先展示 display_name，回退 login_name
        self.assertTrue(
            'nav-admin' in body or 'R10NAVADM' in body,
            '导航未显示当前用户',
        )

    def test_nav_present_on_empty_page(self):
        """无数据的分支也必须带导航（empty 分支容易漏）。"""
        resp = self.client.get('/r5/courses/?q=不存在的课程')
        body = resp.content.decode('utf-8')
        self.assertIn('id="sm-sidebar"', body)

    def test_no_duplicate_csrf_token(self):
        """子模板不应再重复输出 csrf_token（base 已提供）。"""
        resp = self.client.get('/r5/years/')
        body = resp.content.decode('utf-8')
        self.assertEqual(
            body.count('csrfmiddlewaretoken'), 1,
            '页面中出现了多个 csrf token',
        )
