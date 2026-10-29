"""H7：三引擎跨模块 E2E + 并发。

R-15 处理
---------
WebKit 在**同一测试类内连续多个测试**时会登录静默失败（见
`docs/SMASS_R10_WebKit_Root_Cause.md` §6）。因此本文件对 WebKit 采用
**每个场景一个独立测试类（单方法）** 的方式，确保每个场景都在干净状态下执行，
不把未真正执行的场景标为通过。

引擎选择：
    H7_BROWSER=chromium|firefox|webkit|all   (默认 chromium)
"""
import os
import threading
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from r21_account import services as core_services
from r21_account.models import Account, AccountRole, RoleCode
from smass_academic import services as academic_services
from smass_academic.models import AcademicTerm, AcademicYear, Course, TeachingSection
from smass_analytics import services as analytics_services
from smass_organization import services as org_services
from smass_organization.models import OrganizationUnit, StudentRecord
from smass_workflow import services as workflow_services
from smass_workflow.models import ApprovalTask, WorkflowDefinition, WorkflowInstance

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE_ENV = os.environ.get('H7_BROWSER', 'chromium').strip().lower()
ENGINES = ['chromium', 'firefox', 'webkit'] if ENGINE_ENV == 'all' else [ENGINE_ENV]

PASSWORD = 'H7Pass#2024'


def make_account(login, role=RoleCode.SYSTEM_ADMIN, must_change=False):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin')
    account.must_change_password = must_change
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    if role:
        core_services.grant_role(account, role, granted_by='h7')
    return Account.objects.get(pk=account.pk)


class H7Harness(StaticLiveServerTestCase):
    host = '127.0.0.1'
    engine = 'chromium'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sync_playwright is None:
            raise unittest.SkipTest('playwright unavailable: {}'.format(_IMPORT_ERROR))
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, cls.engine, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('engine {} unavailable'.format(cls.engine))
        try:
            cls.browser = launcher.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('{} launch failed: {}'.format(cls.engine, str(exc)[:160]))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        core_services.ensure_role_groups()
        self.admin = make_account('H7ADM')
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 860})
        self.page = self.context.new_page()
        self.page.set_default_timeout(20000)

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def login(self, page=None):
        page = page or self.page
        page.goto(self.live_server_url + '/r21/login/')
        page.fill('#id_login_name', 'H7ADM')
        page.fill('#id_password', PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')

    def no_overflow(self, page):
        return page.evaluate(
            "() => document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth + 1")


# ---------------------------------------------------------------------------
# 场景 1：完整跨模块旅程（R4 -> R5 -> R6 -> R7 -> R8 -> R9）
# ---------------------------------------------------------------------------
class H7JourneyScenario(H7Harness):
    def test_full_cross_module_journey(self):
        page = self.page
        base = self.live_server_url
        self.login()

        # ---- R4：建组织 ----
        page.goto(base + '/r4/units/new/')
        page.wait_for_load_state('load')
        page.fill('#f-code', 'H7-COL')
        page.fill('#f-name', 'H7学院')
        page.select_option('#f-unit_type', 'college')
        page.click('#btn-save')
        page.wait_for_url('**/r4/units/', timeout=20000)
        self.assertTrue(OrganizationUnit.objects.filter(code='H7-COL').exists())

        # ---- R4：学生编辑（版本冲突 409）----
        # 顺序很重要：页面必须**先加载旧版本**，之后后台更新，再提交才会冲突。
        record = StudentRecord.objects.create(
            student_no='H7S001', name='H7学生', unit=OrganizationUnit.objects.get(code='H7-COL'))
        stale = record.version

        page.goto(base + '/r4/students/H7S001/edit/')
        page.wait_for_load_state('load')

        # 页面加载后，后台把记录改到新版本
        org_services.update_student(record, name='他人修改',
                                    expected_version=stale, actor='other')

        # 现在用页面上携带的旧版本号提交 -> 应 409
        page.fill('#f-name', '我的修改')
        page.click('#btn-save')
        page.wait_for_load_state('load')

        body = page.content()
        self.assertIn('已被他人修改', body, '409 冲突提示未出现')
        record.refresh_from_db()
        self.assertEqual(record.name, '他人修改', '冲突时不应覆盖他人修改')

        # ---- R5：建课程 + 教学班 ----
        year = AcademicYear.objects.create(
            code='H7-Y', start_date=__import__('datetime').date(2032, 9, 1),
            end_date=__import__('datetime').date(2033, 8, 31))
        term = AcademicTerm.objects.create(
            year=year, semester='1',
            start_date=__import__('datetime').date(2032, 9, 1),
            end_date=__import__('datetime').date(2033, 1, 15))

        page.goto(base + '/r5/courses/new/')
        page.wait_for_load_state('load')
        page.fill('#f-code', 'H7-C1')
        page.fill('#f-title', 'H7课程')
        page.fill('#f-credit', '3')
        page.click('#btn-save')
        page.wait_for_url('**/r5/courses/', timeout=20000)
        course = Course.objects.get(code='H7-C1')

        page.goto(base + '/r5/sections/new/')
        page.wait_for_load_state('load')
        page.select_option('#f-term', str(term.pk))
        page.select_option('#f-course', str(course.pk))
        page.fill('#f-code', 'A')
        page.fill('#f-capacity', '30')
        page.click('#btn-save')
        page.wait_for_url('**/r5/sections/', timeout=20000)
        self.assertTrue(TeachingSection.objects.filter(
            term=term, course=course, code='A').exists())

        # ---- R6：建流程 + 发起 + 审批 ----
        page.goto(base + '/r6/definitions/new/')
        page.wait_for_load_state('load')
        page.fill('#f-code', 'H7-FLOW')
        page.fill('#f-name', 'H7流程')
        page.select_option('#f-template', 'single')
        page.click('#btn-create')
        page.wait_for_url('**/r6/definitions/**', timeout=20000)
        definition = WorkflowDefinition.objects.get(code='H7-FLOW')

        page.goto(base + '/r6/instances/new/')
        page.wait_for_load_state('load')
        page.select_option('#f-definition', str(definition.pk))
        page.fill('#f-subject_type', 'leave')
        page.fill('#f-subject_id', 'H7-L1')
        page.click('#btn-start')
        page.wait_for_url('**/r6/instances/**', timeout=20000)

        instance = WorkflowInstance.objects.get(subject_id='H7-L1')
        self.assertEqual(instance.status, 'draft')

        page.select_option('#f-action', 'submit')
        page.click('#btn-action')
        page.wait_for_timeout(500)
        page.click('button.sm-btn.is-primary:has-text("确认")')
        page.wait_for_timeout(1200)

        instance.refresh_from_db()
        self.assertEqual(instance.status, 'pending')

        # ---- R7：指标反映 ----
        metric = analytics_services.register_metric(
            'org_units_total', '组织数', 'organization')
        analytics_services.validate_metric(metric)

        page.goto(base + '/r7/dashboard/')
        page.wait_for_load_state('load')
        body = page.content()
        self.assertIn('org_units_total', body)

        # ---- R8 / R9 ----
        page.goto(base + '/r8/docs/')
        page.wait_for_load_state('load')
        self.assertIn('/api/v1/units/', page.content())

        page.goto(base + '/r9/status/')
        page.wait_for_load_state('load')
        self.assertIn('STAGING', page.content())


# ---------------------------------------------------------------------------
# 场景 2：强制改密旅程
# ---------------------------------------------------------------------------
class H7ForcedPasswordScenario(H7Harness):
    def setUp(self):
        super().setUp()
        self.forced = make_account('H7FORCE', must_change=True)

    def test_forced_password_change_journey(self):
        page = self.page
        base = self.live_server_url

        page.goto(base + '/r21/login/')
        page.fill('#id_login_name', 'H7FORCE')
        page.fill('#id_password', PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')

        # 被强制送到改密页
        page.goto(base + '/r4/units/')
        page.wait_for_load_state('load')
        self.assertIn('/r21/change-password/', page.url)

        # 改密
        page.fill('input[name="current_password"]', PASSWORD)
        page.fill('input[name="new_password"]', 'H7New#2024')
        page.fill('input[name="confirm_password"]', 'H7New#2024')
        page.click('button[type="submit"]')
        page.wait_for_load_state('load')

        self.forced.refresh_from_db()
        self.assertFalse(self.forced.must_change_password)

        # 改密后可访问业务页
        page.goto(base + '/r4/units/')
        page.wait_for_load_state('load')
        self.assertIn('/r4/units/', page.url)


# ---------------------------------------------------------------------------
# 场景 3：响应式（三视口）
# ---------------------------------------------------------------------------
class H7ViewportScenario(H7Harness):
    def test_three_viewports_no_overflow(self):
        page = self.page
        base = self.live_server_url
        self.login()

        cases = [
            ('375x812', 375, 812, True),
            ('768x1024', 768, 1024, False),
            ('1280x860', 1280, 860, False),
        ]
        paths = ['/r10/', '/r4/units/', '/r5/sections/', '/r7/dashboard/',
                 '/r8/docs/', '/r9/status/']

        for label, width, height, mobile in cases:
            ctx = self.browser.new_context(
                viewport={'width': width, 'height': height},
                is_mobile=mobile, has_touch=mobile)
            ctx.add_cookies(self.context.cookies())
            page = ctx.new_page()
            page.set_default_timeout(20000)
            page.goto(base + '/r21/login/')
            page.wait_for_load_state('load')

            offenders = []
            for path in paths:
                page.goto(base + path)
                page.wait_for_load_state('load')
                if not self.no_overflow(page):
                    offenders.append(path)
            ctx.close()

            self.assertEqual(offenders, [],
                             '{} 溢出: {}'.format(label, offenders))


# ---------------------------------------------------------------------------
# 场景 4：移动端抽屉 + 空态
# ---------------------------------------------------------------------------
class H7MobileDrawerScenario(H7Harness):
    def test_mobile_drawer_and_empty_state(self):
        base = self.live_server_url
        ctx = self.browser.new_context(
            viewport={'width': 375, 'height': 812}, is_mobile=True, has_touch=True)
        ctx.add_cookies(self.context.cookies())
        page = ctx.new_page()
        page.set_default_timeout(20000)

        page.goto(base + '/r21/login/')
        page.fill('#id_login_name', 'H7ADM')
        page.fill('#id_password', PASSWORD)
        page.click('#btnLogin')
        page.wait_for_load_state('load')

        # 抽屉开合
        page.goto(base + '/r5/years/')
        page.wait_for_load_state('load')
        page.click('#sm-drawer-toggle')
        page.wait_for_timeout(400)
        self.assertTrue(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))

        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
        self.assertFalse(page.evaluate(
            "() => document.getElementById('sm-sidebar').classList.contains('is-open')"))

        # 空态：不存在的搜索
        page.goto(base + '/r5/courses/?q=H7绝对不存在')
        page.wait_for_load_state('load')
        self.assertIn('sm-empty', page.content())

        ctx.close()


# ---------------------------------------------------------------------------
# 并发（不依赖浏览器）
# ---------------------------------------------------------------------------
class H7ConcurrencyTests(TransactionTestCase):
    """并行角色授予与审批任务分配。

    H2 已验证 DB 生成列唯一索引；这里验证**服务层路径**在并发下的行为。
    """

    def setUp(self):
        core_services.ensure_role_groups()
        self.account = make_account('H7CONC', role=None)

    def tearDown(self):
        AccountRole.objects.filter(account=self.account).delete()

    def test_parallel_role_grants_single_active(self):
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def worker(index):
            barrier.wait()
            try:
                core_services.grant_role(
                    Account.objects.get(pk=self.account.pk),
                    RoleCode.TEACHER, granted_by='h7-{}'.format(index))
                outcome = 'ok'
            except IntegrityError:
                outcome = 'duplicate'
            except Exception as exc:  # noqa: BLE001
                outcome = type(exc).__name__
            finally:
                connection.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=40)

        active = AccountRole.objects.filter(
            account=self.account, role=RoleCode.TEACHER,
            revoked_at__isnull=True).count()
        self.assertEqual(active, 1,
                         '并发授予产生 {} 个 active（结果: {}）'.format(active, results))

    def test_parallel_approval_assignment(self):
        definition = workflow_services.create_definition('H7-CONC', 'H7并发')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '发起', 'start')
        workflow_services.add_node(version, 'approve', '审批', 'approval')
        workflow_services.add_node(version, 'end', '完成', 'end')
        workflow_services.add_transition(version, 'start', 'approve', 'submit')
        workflow_services.add_transition(version, 'approve', 'end', 'approve')
        workflow_services.publish_version(version)

        instance = workflow_services.start_instance(
            version, subject_type='conc', subject_id='H7-C1', created_by='h7')

        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(4)
        node = version.nodes.get(code='approve')

        def worker(index):
            barrier.wait()
            try:
                ApprovalTask.objects.create(
                    instance=WorkflowInstance.objects.get(pk=instance.pk),
                    node=node, status='open', assignee='h7-{}'.format(index))
                outcome = 'ok'
            except IntegrityError:
                outcome = 'duplicate'
            except Exception as exc:  # noqa: BLE001
                outcome = type(exc).__name__
            finally:
                connection.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=40)

        open_count = ApprovalTask.objects.filter(
            instance=instance, status='open').count()
        self.assertEqual(open_count, 1,
                         '并发创建 open 任务产生 {} 条（结果: {}）'.format(open_count, results))


# ---------------------------------------------------------------------------
# 按引擎生成类（WebKit 每场景一个单方法类，规避 R-15）
# ---------------------------------------------------------------------------
JOURNEY_CLASSES = [
    H7JourneyScenario,
    H7ForcedPasswordScenario,
    H7ViewportScenario,
    H7MobileDrawerScenario,
]


def _register_engine_classes():
    module = globals()
    for engine in ENGINES:
        if engine == 'chromium':
            continue  # 基类本身即 chromium
        for base in JOURNEY_CLASSES:
            name = '{}On{}'.format(base.__name__, engine.capitalize())
            # WebKit：每个场景已是一个独立类（单方法），天然满足 R-15 隔离
            module[name] = type(name, (base,), {'engine': engine})


_register_engine_classes()
