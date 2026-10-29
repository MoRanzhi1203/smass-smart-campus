"""U1/U2：统一外壳、侧边栏、面包屑、新页面、死链检测。"""
import re
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_analytics import services as analytics_services
from smass_organization import services as org_services
from smass_organization.models import StudentRecord
from smass_workflow import services as workflow_services

PASSWORD = 'U1Pass#2024'

#: 侧边栏里的全部链接（与 base.html 一致）
NAV_LINKS = [
    '/r4/units/', '/r4/students/', '/r4/import/',
    '/r5/years/', '/r5/courses/', '/r5/sections/',
    '/r5/workspace/', '/r5/my-courses/',
    '/r6/definitions/', '/r6/instances/', '/r6/tasks/', '/r6/notifications/',
    '/r7/dashboard/', '/r7/metrics/',
    '/r8/docs/', '/r9/status/',
]


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u1')
    return Account.objects.get(pk=account.pk)


class ShellFixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = make_account('U1ADM', RoleCode.SYSTEM_ADMIN)

        college = org_services.create_unit(code='U1C', name='外壳学院', unit_type='college')
        StudentRecord.objects.create(student_no='U1S1', name='外壳学生', unit=college)

        year = academic_services.create_year('U1-Y', date(2025, 9, 1), date(2026, 8, 31))
        self.term = academic_services.create_term(
            year, '1', date(2025, 9, 1), date(2026, 1, 15))
        self.course = academic_services.create_course('U1-CS', '外壳课程', credit=2)
        academic_services.create_section(self.term, self.course, 'A', capacity=10)

        definition = workflow_services.create_definition('U1-FLOW', '外壳流程')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '开始', 'start')
        workflow_services.add_node(version, 'end', '结束', 'end')
        workflow_services.add_transition(version, 'start', 'end', 'submit')
        workflow_services.publish_version(version)

        metric = analytics_services.register_metric(
            'org_units_total', '组织数', 'organization')
        analytics_services.validate_metric(metric)

        self.client.force_login(self.admin)


class SidebarTests(ShellFixture):
    def test_sidebar_present_on_every_page(self):
        for url in NAV_LINKS:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            body = resp.content.decode('utf-8')
            self.assertIn('id="sm-sidebar"', body, url)

    def test_drawer_toggle_and_backdrop(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('id="sm-drawer-toggle"', body)
        self.assertIn('id="sm-backdrop"', body)
        self.assertIn('aria-controls="sm-sidebar"', body)

    def test_breadcrumb_present(self):
        body = self.client.get('/r5/years/').content.decode('utf-8')
        self.assertIn('sm-breadcrumb', body)
        self.assertIn('首页', body)

    def test_active_state_per_module(self):
        cases = {
            '/r4/units/': '/r4/units/',
            '/r5/years/': '/r5/years/',
            '/r6/definitions/': '/r6/definitions/',
            '/r7/dashboard/': '/r7/dashboard/',
            '/r9/status/': '/r9/status/',
        }
        for url, expected_href in cases.items():
            html = self.client.get(url).content.decode('utf-8')
            # 找到带 is-active 的链接 href
            active = re.findall(
                r'class="sm-nav-link is-active"[^>]*href="([^"]+)"', html)
            active += re.findall(
                r'href="([^"]+)"[^>]*class="sm-nav-link is-active"', html)
            self.assertIn(
                expected_href, active,
                '{} 未高亮 {}，实际 active={}'.format(url, expected_href, active),
            )

    def test_no_dead_links_in_sidebar(self):
        """侧边栏每个链接都必须可达（非 404）。"""
        dead = []
        for url in NAV_LINKS:
            resp = self.client.get(url)
            if resp.status_code == 404:
                dead.append(url)
            self.assertNotEqual(
                resp.status_code, 404, '{} 是死链'.format(url))
        self.assertEqual(dead, [])

    def test_identity_shown_without_username_attribute(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('U1ADM', body)
        self.assertIn('id="nav-logout"', body)


class NewPageTests(ShellFixture):
    def test_import_page(self):
        resp = self.client.get('/r4/import/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="csv-input"', body)
        self.assertIn('id="btn-preview"', body)
        self.assertIn('id="btn-commit"', body)

    def test_api_docs_page(self):
        resp = self.client.get('/r8/docs/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="endpoint-table"', body)
        self.assertIn('/api/v1/units/', body)
        self.assertIn('read:students', body)

    def test_ops_status_page(self):
        resp = self.client.get('/r9/status/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertIn('id="probe-table"', body)
        self.assertIn('STAGING', body)

    def test_import_page_requires_admin(self):
        teacher = make_account('U1T', RoleCode.TEACHER, 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(self.client.get('/r4/import/').status_code, 403)

    def test_anonymous_denied_on_new_pages(self):
        self.client.logout()
        for url in ('/r4/import/', '/r8/docs/', '/r9/status/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)


class DesignSystemTests(ShellFixture):
    def test_css_and_js_loaded(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('css/r10.css', body)
        self.assertIn('js/r10.js', body)

    def test_module_pages_use_design_classes(self):
        for url in ('/r4/units/', '/r5/years/', '/r6/definitions/', '/r7/dashboard/'):
            body = self.client.get(url).content.decode('utf-8')
            self.assertIn('sm-table', body, url)
            self.assertIn('sm-page-head', body, url)

    def test_no_legacy_border_tables(self):
        for url in ('/r4/units/', '/r5/years/', '/r7/dashboard/'):
            body = self.client.get(url).content.decode('utf-8')
            self.assertNotIn('border="1"', body, url)

    def test_empty_state_rendered(self):
        """空数据分支要显示 sm-empty。"""
        body = self.client.get('/r5/courses/?q=绝对不存在的课程').content.decode('utf-8')
        self.assertIn('sm-empty', body)
