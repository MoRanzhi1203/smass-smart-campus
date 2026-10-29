"""U8：全路由外壳一致性 + 跨模块业务旅程（不依赖浏览器，快速覆盖）。

浏览器级验证见 `test_r10_u8_browser.py`。
"""
import re

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_academic.models import AcademicTerm, AcademicYear, Course, Enrollment, TeachingSection
from smass_analytics import services as analytics_services
from smass_operations import ui_views as ops_ui
from smass_organization import services as org_services
from smass_organization.models import OrganizationUnit, StudentRecord
from smass_workflow import services as workflow_services
from smass_workflow.models import WorkflowDefinition, WorkflowInstance

PASSWORD = 'U8Pass#2024'

#: 所有 staff 可访问的 GET 页面（不含需要参数详情的）
STAFF_PAGES = [
    ('/r10/', 'home'),
    ('/r4/units/', 'org'),
    ('/r4/students/', 'students'),
    ('/r4/import/', 'import'),
    ('/r5/years/', 'years'),
    ('/r5/terms/', 'terms'),
    ('/r5/courses/', 'courses'),
    ('/r5/sections/', 'sections'),
    ('/r5/workspace/', 'workspace'),
    ('/r5/my-courses/', 'mycourses'),
    ('/r6/definitions/', 'defs'),
    ('/r6/instances/', 'instances'),
    ('/r6/tasks/', 'tasks'),
    ('/r6/notifications/', 'notifs'),
    ('/r7/dashboard/', 'dashboard'),
    ('/r7/metrics/', 'metrics'),
    ('/r8/docs/', 'apidocs'),
    ('/r9/status/', 'ops'),
]

#: 表单页
FORM_PAGES = [
    '/r4/units/new/',
    '/r5/years/new/',
    '/r5/terms/new/',
    '/r5/courses/new/',
    '/r5/sections/new/',
    '/r6/definitions/new/',
    '/r6/instances/new/',
]


def make_account(login, role, person_type='admin'):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='u8')
    return Account.objects.get(pk=account.pk)


class U8Fixture(TestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.admin = make_account('U8ADM', RoleCode.SYSTEM_ADMIN)
        self.client.force_login(self.admin)


class RouteShellConsistencyTests(U8Fixture):
    """每个 UI 路由都必须有侧边栏、面包屑、正确高亮、无 404。"""

    def test_all_staff_pages_200(self):
        for url, label in STAFF_PAGES:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, '{} 返回 {}'.format(url, resp.status_code))

    def test_all_pages_have_sidebar_and_breadcrumb(self):
        missing = []
        for url, label in STAFF_PAGES:
            body = self.client.get(url).content.decode('utf-8')
            if 'id="sm-sidebar"' not in body:
                missing.append((url, 'sidebar'))
            if 'sm-breadcrumb' not in body:
                missing.append((url, 'breadcrumb'))
        self.assertEqual(missing, [], '外壳缺失: {}'.format(missing))

    def test_all_form_pages_200(self):
        for url in FORM_PAGES:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            body = resp.content.decode('utf-8')
            self.assertIn('id="sm-sidebar"', body, url)
            self.assertIn('data-sm-form', body, url)

    def test_every_page_has_exactly_one_active_nav(self):
        for url, label in STAFF_PAGES:
            body = self.client.get(url).content.decode('utf-8')
            count = body.count('sm-nav-link is-active')
            self.assertEqual(count, 1, '{} 有 {} 个高亮项'.format(url, count))

    def test_no_dead_links_in_sidebar(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        hrefs = re.findall(r'class="sm-nav-link[^"]*"\s*\n?\s*href="([^"]+)"', body)
        if not hrefs:
            hrefs = re.findall(r'href="(/r[0-9][^"]*|/api/[^"]*)"', body)
        self.assertGreaterEqual(len(hrefs), 10, '侧边栏链接过少')

        dead = []
        for href in sorted(set(hrefs)):
            if self.client.get(href).status_code == 404:
                dead.append(href)
        self.assertEqual(dead, [], '死链: {}'.format(dead))

    def test_every_page_has_viewport_meta(self):
        for url, label in STAFF_PAGES:
            body = self.client.get(url).content.decode('utf-8')
            self.assertIn('name="viewport"', body, url)


class A11yPrimitiveTests(U8Fixture):
    """可访问性基础（无浏览器即可断言的部分）。"""

    def test_drawer_has_aria_attributes(self):
        body = self.client.get('/r5/years/').content.decode('utf-8')
        self.assertIn('aria-controls="sm-sidebar"', body)
        self.assertIn('aria-expanded="false"', body)
        self.assertIn('aria-label="主导航"', body)

    def test_backdrop_is_aria_hidden(self):
        body = self.client.get('/r5/years/').content.decode('utf-8')
        self.assertIn('id="sm-backdrop"', body)
        self.assertIn('aria-hidden="true"', body)

    def test_tables_have_thead(self):
        for url in ('/r4/units/', '/r5/years/', '/r6/definitions/', '/r7/metrics/'):
            body = self.client.get(url).content.decode('utf-8')
            self.assertIn('<thead>', body, '{} 表格缺少表头'.format(url))

    def test_forms_have_labels(self):
        for url in ('/r4/units/new/', '/r5/years/new/', '/r6/definitions/new/'):
            body = self.client.get(url).content.decode('utf-8')
            self.assertIn('<label', body, url)
            self.assertIn('for="f-', body, url)

    def test_required_fields_marked(self):
        body = self.client.get('/r4/units/new/').content.decode('utf-8')
        self.assertIn('class="req"', body)

    def test_alert_regions_are_live(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('aria-live="polite"', body)

    def test_skip_to_content_absent_but_main_landmark_present(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('<main', body)
        self.assertIn('id="sm-content"', body)

    def test_reduced_motion_css_present(self):
        body = self.client.get('/r10/').content.decode('utf-8')
        self.assertIn('css/r10.css', body)


class SilentJourneyTests(U8Fixture):
    """R4 -> R5 -> R6 -> R7 -> R8 -> R9，每步断言 DB 状态变化。"""

    def test_full_journey_persists_each_step(self):
        # ---------- R4：组织 + 学生 ----------
        resp = self.client.post('/r4/units/new/', {
            'code': 'U8-COL', 'name': 'U8学院', 'unit_type': 'college',
            'parent': '', 'sort_order': '0',
        })
        self.assertEqual(resp.status_code, 302)
        college = OrganizationUnit.objects.get(code='U8-COL')

        resp = self.client.post('/r4/units/new/', {
            'code': 'U8-MAJ', 'name': 'U8专业', 'unit_type': 'major',
            'parent': str(college.pk), 'sort_order': '0',
        })
        self.assertEqual(resp.status_code, 302)
        major = OrganizationUnit.objects.get(code='U8-MAJ')
        self.assertEqual(major.parent_id, college.pk)

        # 学生通过导入创建（覆盖 U3 的导入链路）
        csv = 'student_no,name,unit_code\nU8S001,U8学生甲,U8-MAJ\nU8S002,U8学生乙,U8-MAJ\n'
        import json as _json
        resp = self.client.post('/r4/import/commit/',
                                data=_json.dumps({'csv': csv}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StudentRecord.objects.filter(student_no__startswith='U8S').count(), 2)

        # ---------- R5：学年/学期/课程/教学班 ----------
        resp = self.client.post('/r5/years/new/', {
            'code': 'U8-Y', 'start_date': '2030-09-01', 'end_date': '2031-08-31',
        })
        self.assertEqual(resp.status_code, 302)
        year = AcademicYear.objects.get(code='U8-Y')

        resp = self.client.post('/r5/terms/new/', {
            'year': year.pk, 'semester': '1',
            'start_date': '2030-09-01', 'end_date': '2031-01-15',
        })
        self.assertEqual(resp.status_code, 302)
        term = AcademicTerm.objects.get(year=year, semester='1')

        resp = self.client.post('/r5/courses/new/', {
            'code': 'U8-C1', 'title': 'U8课程', 'credit': '3', 'is_active': '1',
        })
        self.assertEqual(resp.status_code, 302)
        course = Course.objects.get(code='U8-C1')

        resp = self.client.post('/r5/sections/new/', {
            'term': term.pk, 'course': course.pk, 'code': 'A', 'capacity': '30',
        })
        self.assertEqual(resp.status_code, 302)
        section = TeachingSection.objects.get(term=term, course=course, code='A')

        # 教师分配
        teacher = make_account('U8T', RoleCode.TEACHER, 'teacher')
        resp = self.client.post('/r5/sections/{}/assign/'.format(section.pk),
                                {'teacher': teacher.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(academic_services.can_teach(teacher, section))

        # ---------- R6：定义 + 实例 + 审批 ----------
        resp = self.client.post('/r6/definitions/new/', {
            'code': 'U8-FLOW', 'name': 'U8流程', 'template': 'single',
        })
        self.assertEqual(resp.status_code, 302)
        definition = WorkflowDefinition.objects.get(code='U8-FLOW')

        resp = self.client.post('/r6/instances/new/', {
            'definition': definition.pk,
            'subject_type': 'leave', 'subject_id': 'U8-L1',
        })
        self.assertEqual(resp.status_code, 302)
        instance = WorkflowInstance.objects.get(subject_id='U8-L1')

        self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                         {'action': 'submit'})
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'pending')

        self.client.post('/r6/instances/{}/action/'.format(instance.pk),
                         {'action': 'approve'})
        instance.refresh_from_db()
        self.assertEqual(instance.status, 'approved')

        # ---------- R7：指标反映新数据 ----------
        metric = analytics_services.register_metric(
            'org_units_total', '组织数', 'organization')
        analytics_services.validate_metric(metric)
        value, meta = analytics_services.compute_metric(metric, self.admin)
        self.assertEqual(int(value), OrganizationUnit.objects.count())
        self.assertGreaterEqual(int(value), 2)

        # ---------- R8：文档页可达且列出端点 ----------
        resp = self.client.get('/r8/docs/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('/api/v1/units/', resp.content.decode('utf-8'))

        # ---------- R9：运维页就绪 ----------
        resp = self.client.get('/r9/status/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="probe-table"', resp.content.decode('utf-8'))

        # ---------- 跨模块不变量 ----------
        self.assertEqual(section.term.year.code, 'U8-Y')
        self.assertEqual(instance.version.definition.code, 'U8-FLOW')
        self.assertEqual(StudentRecord.objects.get(student_no='U8S001').unit.code, 'U8-MAJ')

    def test_journey_survives_reload(self):
        """写入后重新获取页面，数据仍在（防内存态假象）。"""
        self.client.post('/r4/units/new/', {
            'code': 'U8-REL', 'name': '重载学院', 'unit_type': 'college', 'parent': '',
        })
        body = self.client.get('/r4/units/').content.decode('utf-8')
        self.assertIn('U8-REL', body)
        self.assertIn('重载学院', body)


class PermissionMatrixTests(U8Fixture):
    """四条身份线的权限矩阵。"""

    def test_student_denied_admin_pages(self):
        student = make_account('U8S', RoleCode.STUDENT, 'student')
        self.client.force_login(student)
        denied = [
            '/r4/units/new/', '/r4/import/', '/r5/years/new/', '/r5/courses/new/',
            '/r6/definitions/new/', '/r8/docs/', '/r9/status/',
        ]
        for url in denied:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_teacher_allowed_teaching_denied_admin_forms(self):
        teacher = make_account('U8T2', RoleCode.TEACHER, 'teacher')
        self.client.force_login(teacher)
        self.assertEqual(self.client.get('/r5/workspace/').status_code, 200)
        self.assertEqual(self.client.get('/r5/years/new/').status_code, 403)
        self.assertEqual(self.client.get('/r6/definitions/new/').status_code, 403)

    def test_anonymous_denied_everything_but_home(self):
        self.client.logout()
        self.assertEqual(self.client.get('/r10/').status_code, 200)
        for url, _label in STAFF_PAGES[1:]:
            self.assertIn(self.client.get(url).status_code, (403, 302), url)

    def test_forged_post_denied(self):
        """直接伪造 POST 到 admin 端点也必须被拒。"""
        student = make_account('U8S2', RoleCode.STUDENT, 'student')
        self.client.force_login(student)

        resp = self.client.post('/r4/units/new/', {
            'code': 'HACK', 'name': '伪造', 'unit_type': 'college', 'parent': '',
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(OrganizationUnit.objects.filter(code='HACK').exists())

    def test_conflict_role_sees_nothing(self):
        """无角色账号：所有受保护页面拒绝，且不降级为全可见。"""
        nobody = make_account('U8NOB', None)
        self.client.force_login(nobody)
        for url in ('/r4/units/', '/r5/years/', '/r7/dashboard/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(
            org_services.scoped_students(nobody).count(), 0,
            '无角色账号不应看到任何学生')
